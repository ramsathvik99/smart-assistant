# plugins/example_plugin.py

# A plugin must define which intents it handles
INTENTS = ["HELLO_PLUGIN", "PLUGIN_TEST"]

def run(text, context=None):
    """
    Standard entry point for plugins.
    """
    if "test" in text.lower():
        return "The example plugin is working perfectly! I can see your context too."
    return "Hello from the new plugin architecture!"
