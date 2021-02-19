import json


LIBAPI = 3
LIBPATCH = 0


def send_relation_data(relation, app, port, addrs):
    if port != relation.data[app].get("port", None):
        relation.data[app]["port"] = port

    if addrs != json.loads(relation.data[app].get("addrs", "null")):
        relation.data[app]["addrs"] = json.dumps(addrs)


def get_relation_data(event):
    return {
        "addrs": json.loads(event.relation.data[event.app].get("addrs", "[]")),
        "port": event.relation.data[event.app]["port"],
    }
