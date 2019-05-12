import pytest
import os
from mock import Mock
from brewtils.resolver import ParameterResolver


@pytest.fixture
def bytes_param():
    return {
        "type": "test",
        "filename": "testfile",
        "content_type": "text/plain",
        "id": "5cd2152c759cb4d72646a59a",
    }


@pytest.fixture
def test_resolvers():
    return {"test": Mock()}


class TestPluginResolver(object):
    @pytest.mark.parametrize("params", [({"foo": "bar"}), ({})])
    def test_trivial_resolve(self, tmpdir, params, test_resolvers):
        resolver = ParameterResolver(params, [], tmpdir, test_resolvers)
        resolver.resolve()
        assert resolver.resolved_parameters == params

    def test_resolve(self, tmpdir, bytes_param, test_resolvers):
        resolver = ParameterResolver(
            {"bytes": bytes_param}, [["bytes"]], tmpdir, test_resolvers
        )
        resolver.resolve()
        params = resolver.resolved_parameters

        assert "bytes" in params
        assert [os.path.basename(f) for f in tmpdir.listdir()] == [
            bytes_param["filename"]
        ]
        assert isinstance(params["bytes"])
        tmpdir.remove()
