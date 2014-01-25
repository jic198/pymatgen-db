"""
Utility functions used across scripts
"""
__author__ = "Shyue Ping Ong"
__copyright__ = "Copyright 2012, The Materials Project"
__version__ = "1.1"
__maintainer__ = "Shyue Ping Ong"
__email__ = "shyue@mit.edu"
__date__ = "Dec 1, 2012"

import bson
import datetime
import json
import os
from pymongo import Connection


DEFAULT_PORT = 27017

DEFAULT_SETTINGS = [
    ("host", "localhost"),
    ("port", DEFAULT_PORT),
    ("database", "vasp"),
    ("admin_user", None),
    ("admin_password", None),
    ("readonly_user", None),
    ("readonly_password", None),
    ("collection", "tasks"),
    ("aliases_config", None),
    ("mapi_key", None)
]


def get_settings(config_file):
    if config_file:
        with open(config_file) as f:
            return json.load(f)
    elif os.path.exists("db.json"):
        with open("db.json") as f:
            return json.load(f)
    else:
        return dict(DEFAULT_SETTINGS)


def get_database(config_file, admin=False):
    d = get_settings(config_file)
    conn = Connection(d["host"], d["port"])
    db = conn[d["database"]]
    user = d["admin_user"] if admin else d["readonly_user"]
    passwd = d["admin_password"] if admin else d["readonly_password"]
    db.authenticate(user, passwd)
    return db


def get_collection(config_file, admin=False):
    db = get_database(config_file, admin=admin)
    settings = get_settings(config_file)
    return db[settings["collection"]]


class MongoJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, bson.objectid.ObjectId):
            return str(o)
        if isinstance(o, datetime.datetime):
            return o.isoformat()
        return json.JSONEncoder.default(self, o)
