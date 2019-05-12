class GridfsResolver(object):
    def __init__(self, client):
        self.client = client

    def resolve(self, bytes_value, writer):
        file_id = bytes_value["id"]
        self.client.stream_to_file(file_id, writer)

    #     self.client.client.session.get()
    #     url = "http://localhost:2337/api/vbeta/files/%s" % file_id
    #     with requests.get(url, stream=True) as response:
    #         response.raise_for_status()
    #         with open(full_path, "wb") as fd:
    #             for chunk in response.iter_content(chunk_size=4096):
    #                 fd.write(chunk)
    #         self._open_file(full_path)
    #     return fd
    #
    # def _open_file(self, full_path):
    #     fd = open(full_path, "rb")
    #     self._open_files.append((full_path, fd))
    #     return fd
    #
    # def cleanup(self):
    #     pass
    #
    # @staticmethod
    # def _index_of(arr, val):
    #     try:
    #         return arr.index(val)
    #     except ValueError:
    #         return -1
