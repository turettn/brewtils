# -*- coding: utf-8 -*-

from concurrent.futures import Future

import pytest
from mock import Mock, MagicMock
from pika.exceptions import AMQPConnectionError

import brewtils.request_consumer
from brewtils.errors import DiscardMessageException, RepublishRequestException
from brewtils.request_consumer import RequestConsumer


@pytest.fixture
def callback_future():
    return Future()


@pytest.fixture
def callback(callback_future):
    return Mock(return_value=callback_future)


@pytest.fixture
def panic_event():
    return Mock()


@pytest.fixture
def channel():
    return Mock()


@pytest.fixture()
def connection():
    return Mock()


@pytest.fixture()
def reconnection():
    return Mock()


@pytest.fixture()
def select_mock(connection, reconnection):
    return Mock(side_effect=[connection, reconnection])


@pytest.fixture
def consumer(monkeypatch, connection, channel, callback, panic_event, select_mock):
    monkeypatch.setattr(brewtils.request_consumer, "SelectConnection", select_mock)

    consumer = RequestConsumer(
        thread_name="Request Consumer",
        connection_info={
            "host": "localhost",
            "port": 5672,
            "user": "guest",
            "password": "guest",
            "virtual_host": "/",
            "ssl": {
                "enabled": False,
                "ca_cert": None,
                "ca_verify": True,
                "client_cert": None,
            },
        },
        amqp_url="amqp://guest:guest@localhost:5672/",
        queue_name="echo.1-0-0-dev0.default",
        on_message_callback=callback,
        panic_event=panic_event,
        max_concurrent=1,
    )
    consumer._channel = channel
    return consumer


class TestRequestConsumer(object):
    def test_run(self, consumer, connection):
        consumer.run()

        assert consumer._connection == connection
        assert connection.ioloop.start.called is True

    def test_stop(self, consumer):
        channel_mock = Mock()
        consumer._channel = channel_mock

        consumer.stop()
        assert consumer.shutdown_event.is_set() is True
        assert channel_mock.close.called is True

    @pytest.mark.parametrize(
        "body,cb_arg", [("message", "message"), (b"message", "message")]
    )
    def test_on_message(self, consumer, callback, callback_future, body, cb_arg):
        properties = Mock()
        callback_complete = Mock()

        consumer.on_message_callback_complete = callback_complete

        consumer.on_message(Mock(), Mock(), properties, body)
        callback.assert_called_with(cb_arg, properties.headers)

        callback_future.set_result(None)
        assert callback_complete.called is True

    @pytest.mark.parametrize(
        "ex,requeue", [(DiscardMessageException, False), (ValueError, True)]
    )
    def test_on_message_exception(self, consumer, channel, callback, ex, requeue):
        basic_deliver = Mock()

        callback.side_effect = ex

        consumer.on_message(Mock(), basic_deliver, Mock(), Mock())
        channel.basic_nack.assert_called_once_with(
            basic_deliver.delivery_tag, requeue=requeue
        )


class TestCallbackComplete(object):
    def test_success(self, consumer, channel, callback_future):
        basic_deliver = Mock()

        callback_future.set_result(None)
        consumer.on_message_callback_complete(basic_deliver, callback_future)
        channel.basic_ack.assert_called_once_with(basic_deliver.delivery_tag)

    def test_ack_error(self, consumer, channel, callback_future, panic_event):
        basic_deliver = Mock()
        channel.basic_ack.side_effect = ValueError

        callback_future.set_result(None)
        consumer.on_message_callback_complete(basic_deliver, callback_future)
        channel.basic_ack.assert_called_once_with(basic_deliver.delivery_tag)
        assert panic_event.set.called is True

    def test_republish(
        self, monkeypatch, consumer, channel, callback_future, bg_request
    ):
        basic_deliver = Mock()

        blocking_connection = MagicMock()
        publish_channel = Mock()
        publish_connection = MagicMock()
        publish_connection.channel.return_value = publish_channel
        blocking_connection.return_value.__enter__.return_value = publish_connection
        monkeypatch.setattr(
            brewtils.request_consumer, "BlockingConnection", blocking_connection
        )

        callback_future.set_exception(RepublishRequestException(bg_request, {}))

        consumer.on_message_callback_complete(basic_deliver, callback_future)
        channel.basic_ack.assert_called_once_with(basic_deliver.delivery_tag)
        assert publish_channel.basic_publish.called is True

        publish_args = publish_channel.basic_publish.call_args[1]
        assert publish_args["exchange"] == basic_deliver.exchange
        assert publish_args["routing_key"] == basic_deliver.routing_key
        assert bg_request.id in publish_args["body"]

        publish_props = publish_args["properties"]
        assert publish_props.app_id == "beer-garden"
        assert publish_props.content_type == "text/plain"
        assert publish_props.priority == 1
        assert publish_props.headers["request_id"] == bg_request.id

    def test_republish_failure(
        self, monkeypatch, consumer, callback_future, panic_event
    ):
        monkeypatch.setattr(
            brewtils.request_consumer,
            "BlockingConnection",
            Mock(side_effect=ValueError),
        )

        callback_future.set_exception(RepublishRequestException(Mock(), {}))
        consumer.on_message_callback_complete(Mock(), callback_future)
        assert panic_event.set.called is True

    def test_discard_message(self, consumer, channel, callback_future, panic_event):
        callback_future.set_exception(DiscardMessageException())
        consumer.on_message_callback_complete(Mock(), callback_future)
        assert channel.basic_nack.called is True
        assert panic_event.set.called is False

    def test_unknown_exception(self, consumer, callback_future, panic_event):
        callback_future.set_exception(ValueError())
        consumer.on_message_callback_complete(Mock(), callback_future)
        assert panic_event.set.called is True


class TestOpenConnection(object):
    def test_success(self, consumer, connection, select_mock):
        assert consumer.open_connection() == connection
        assert select_mock.called is True

    def test_shutdown_set(self, consumer, select_mock):
        consumer.shutdown_event.set()
        assert consumer.open_connection() is None
        assert select_mock.called is False

    def test_retry(self, consumer, connection, select_mock):
        select_mock.side_effect = [AMQPConnectionError, connection]
        assert consumer.open_connection() == connection
        assert select_mock.call_count == 2

    def test_no_retries(self, consumer, connection, select_mock):
        select_mock.side_effect = AMQPConnectionError
        consumer._max_connect_retries = 0

        with pytest.raises(AMQPConnectionError):
            consumer.open_connection()


def test_on_connection_open(consumer, connection):
    consumer._connection = connection

    consumer.on_connection_open(Mock())
    connection.add_on_close_callback.assert_called_once_with(
        consumer.on_connection_closed
    )
    assert connection.channel.called is True


def test_close_connection(consumer, connection):
    consumer._connection = connection

    consumer.close_connection()
    assert connection.close.called is True


class TestOnConnectionClosed(object):
    def test_shutdown_set(self, consumer, connection):
        consumer._connection = connection
        consumer.shutdown_event.set()

        consumer.on_connection_closed(Mock(), 200, "text")
        assert connection.ioloop.stop.called is True
        assert consumer._channel is None

    def test_shutdown_unset(self, consumer, connection):
        consumer._connection = connection

        consumer.on_connection_closed(Mock(), 200, "text")
        connection.add_timeout.assert_called_with(5, consumer.reconnect)
        assert connection.ioloop.stop.called is False
        assert consumer._channel is None

    def test_closed_by_server(self, consumer, connection):
        consumer._connection = connection

        consumer.on_connection_closed(Mock(), 320, "text")
        assert connection.ioloop.stop.called is True
        assert consumer._channel is None


def test_reconnect_not_shutting_down(consumer, connection, reconnection):
    # Call run instead of just assigning so we get correct select_mock behavior
    consumer.run()
    assert consumer._connection == connection

    consumer.reconnect()
    assert consumer._connection == reconnection
    assert connection.ioloop.stop.called is True
    assert reconnection.ioloop.start.called is True


def test_reconnect_shutting_down(consumer, connection, reconnection):
    # Call run instead of just assigning so we get correct select_mock behavior
    consumer.run()
    assert consumer._connection == connection

    consumer.shutdown_event.set()
    consumer.reconnect()
    assert consumer._connection != reconnection
    assert connection.ioloop.stop.called is True
    assert reconnection.ioloop.start.called is False


def test_open_channel(consumer, connection):
    consumer._connection = connection
    consumer.open_channel()
    connection.channel.assert_called_with(on_open_callback=consumer.on_channel_open)


def test_on_channel_open(consumer):
    fake_channel = Mock()

    consumer.on_channel_open(fake_channel)
    assert consumer._channel == fake_channel
    fake_channel.add_on_close_callback.assert_called_with(consumer.on_channel_closed)


def test_close_channel(consumer, channel):
    consumer.close_channel()
    assert channel.close.called is True


def test_on_channel_closed(consumer, connection):
    consumer._connection = connection
    consumer.on_channel_closed(MagicMock(), 200, "text")
    assert connection.close.called is True


def test_start_consuming(consumer, channel):
    consumer.start_consuming()
    channel.add_on_cancel_callback.assert_called_with(consumer.on_consumer_cancelled)
    channel.basic_qos.assert_called_with(prefetch_count=1)
    channel.basic_consume.assert_called_with(
        consumer.on_message, queue=consumer._queue_name
    )
    assert consumer._consumer_tag == channel.basic_consume.return_value


def test_stop_consuming(consumer, channel):
    consumer_tag = Mock()
    consumer._consumer_tag = consumer_tag

    consumer.stop_consuming()
    channel.basic_cancel.assert_called_with(consumer.on_cancelok, consumer_tag)


def test_on_consumer_cancelled(consumer, channel):
    consumer.on_consumer_cancelled(Mock())
    assert channel.close.called is True


def test_on_cancelok(consumer):
    # This doesn't do anything, just make sure it doesn't raise I guess?
    consumer.on_cancelok(Mock())
