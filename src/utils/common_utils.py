import os 
import yaml
import json

class CommonUtils():

    @staticmethod
    def load_yaml(filepath):
        """
        Utility function to load a yaml file
        """
        if os.path.exists(filepath):
            with open(filepath) as f:
                config = yaml.load(f, Loader=yaml.SafeLoader)
            return config
        else:
            return None

    @staticmethod
    def sort_json(json_obj):
        """
        Sort a JSON object such that keys with simple values come first, followed by
        keys with complex values (list or dict).
        """
        # Separate simple values (strings, numbers, etc.) and complex values (lists, dicts)
        simple_values = {}
        complex_values = {}

        for key, value in json_obj.items():
            if isinstance(value, (dict, list)):
                complex_values[key] = value
            else:
                simple_values[key] = value

        # Combine simple values first, followed by complex values
        sorted_json = {**simple_values, **complex_values}

        return sorted_json

    @staticmethod
    def merge_properties(base_properties, extended_properties):
        """
        Merge base configuration into the extended configuration.
        If properties are present in both, the extended configuration's values will override.
        """
        merged = base_properties.copy()  # Make a copy of the base configuration

        # Merge properties recursively, if both configurations have 'properties' key
        merged = CommonUtils.merge_dicts(base_properties, extended_properties)

        return merged

    @staticmethod
    def merge_dicts(base_dict, extended_dict):
        """
        Recursively merge two dictionaries. In case of conflicts, values from the extended_dict
        will overwrite those in base_dict.
        """
        merged = base_dict.copy()
        for key, value in extended_dict.items():
            if isinstance(value, dict) and key in base_dict and isinstance(base_dict[key], dict):
                merged[key] = CommonUtils.merge_dicts(base_dict[key], value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def load_from_json(file_path):
        """
        Loads configurations from a JSON file and returns them as a list of dictionaries.
        The JSON file is expected to be in the same directory as the script.
        """
        with open(file_path, 'r') as f:
            return json.load(f)
    
    @staticmethod
    def get_class_instance(self, class_path, config_parameters=None):
        clazz_instance = None
        module_name, class_name = class_path.rsplit('.', 1)  # Split the class path into module and class
        module = importlib.import_module(module_name)  # Import the module
        clazz = getattr(module, class_name)  # Get the class from the module
        # Instantiate the class with the specific configuration
        if config_parameters:
            clazz_instance = clazz(config_parameters)
        else:
            clazz_instance = clazz()
        return clazz_instance
    

    @staticmethod
    def load_class(self, class_path):
        clazz_instance = None
        module_name, class_name = class_path.rsplit('.', 1)  # Split the class path into module and class
        module = importlib.import_module(module_name)  # Import the module
        clazz = getattr(module, class_name)  # Get the class from the module
        return clazz

    def read_properties(file_path):
        props = {}
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    props[key.strip()] = value.strip()
        return props
    