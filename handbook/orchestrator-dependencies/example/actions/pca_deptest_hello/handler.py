def handler(context, inputs):
    """The action's whole job is to exist: its environment binding is what the deploy rewrites."""
    return {"greeting": f"hello, {inputs.get('who') or 'world'}"}
