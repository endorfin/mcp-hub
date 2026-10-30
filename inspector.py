from sessions import RpcError, open_session

sessions = {}


def connect(name, entry, pass_environment):
    disconnect(name)
    session = open_session(name, entry, pass_environment, "mcp-hub-inspector")
    sessions[name] = session
    try:
        info = session.initialize()
    except RpcError as e:
        sessions.pop(name, None)
        session.close()
        raise RpcError(f"{e}\n\n" + "\n".join(
            str(x["data"]) for x in session.log if x["kind"] in ("stderr", "stdout", "exit", "error"))[-4000:])
    capabilities = info.get("capabilities", {})
    catalog = {"tools": [], "resources": [], "resourceTemplates": [], "prompts": []}
    if "tools" in capabilities:
        catalog["tools"] = session.list_all("tools/list", "tools")
    if "resources" in capabilities:
        catalog["resources"] = session.list_all("resources/list", "resources")
        try:
            catalog["resourceTemplates"] = session.list_all("resources/templates/list", "resourceTemplates")
        except RpcError:
            pass
    if "prompts" in capabilities:
        catalog["prompts"] = session.list_all("prompts/list", "prompts")
    return {"initialize": info, **catalog}


def call(name, method, params):
    session = sessions.get(name)
    if not session or not session.alive():
        raise RpcError("Not connected")
    return session.request(method, params, timeout=300)


def disconnect(name):
    session = sessions.pop(name, None)
    if session:
        session.close()


def disconnect_all():
    for name in list(sessions):
        disconnect(name)


def log(name, since=0):
    session = sessions.get(name)
    if not session:
        return {"connected": False, "entries": []}
    return {
        "connected": session.alive(),
        "entries": [x for x in session.log if x["t"] > since],
    }
