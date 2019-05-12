import shutil
import os


class ParameterResolver(object):
    def __init__(self, parameters, keys, working_directory, resolvers):
        self.parameters = parameters
        self.keys = keys
        self.working_directory = working_directory
        self.resolvers = resolvers
        self._open_files = []

    def __enter__(self):
        try:
            return self.resolve()
        except Exception:
            self.cleanup()
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def cleanup(self):
        if not os.path.isdir(self.working_directory):
            return

        shutil.rmtree(self.working_directory)

    def resolve(self):
        if not self.keys:
            return self.parameters

        self._ensure_working_dir()
        resolved_parameters = {}
        top_level_keys = [k[0] for k in self.keys]
        for key, value in self.parameters.items():
            index = self._index_of(top_level_keys, key)
            if index == -1:
                resolved_parameters[key] = value
            else:
                resolved_parameters[key] = self._recurse_and_resolve(
                    key, value, index, self.keys
                )
        return resolved_parameters

    def _recurse_and_resolve(self, key, value, index, keys):
        if len(keys[index]) == 1:
            return self._resolve(value)

        raise NotImplementedError("Have not handled the recursive case yet")

    def _resolve(self, value):
        resolve_type = value["type"]
        if resolve_type not in self.resolvers:
            raise KeyError("No resolver found for %s" % resolve_type)

        filename = value["filename"]
        resolver = self.resolvers[value["type"]]
        full_path = os.path.join(self.working_directory, filename)
        with open(full_path, "wb") as file_to_write:
            resolver.resolve(value, file_to_write)
        return self._open_file(full_path)

        # for chunk in resolver.resolve(value, 4096):
        #     filename = value["filename"]
        #     self._write_to_disk(readable, full_path)
        # return self._open_file(full_path)
        # file_id = value["id"]
        # url = "http://localhost:2337/api/vbeta/files/%s" % file_id
        # with requests.get(url, stream=True) as response:
        #     response.raise_for_status()
        #     with open(full_path, "wb") as fd:
        #         for chunk in response.iter_content(chunk_size=4096):
        #             fd.write(chunk)
        #     self._open_file(full_path)
        # return fd

    def _open_file(self, full_path):
        fd = open(full_path, "rb")
        self._open_files.append((full_path, fd))
        return fd

    def _ensure_working_dir(self):
        if not os.path.isdir(self.working_directory):
            os.makedirs(self.working_directory)

    @staticmethod
    def _index_of(arr, val):
        try:
            return arr.index(val)
        except ValueError:
            return -1
