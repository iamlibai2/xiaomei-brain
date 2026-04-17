# Xiaomei Brain

A general-purpose AI Agent framework built with Python and OpenAI API.

## Features

- **ReAct Loop**: Reason-Act-Observe pattern for autonomous tool use
- **Tool System**: Decorator-based tool registration with JSON Schema
- **Builtin Tools**: Shell commands, file read/write
- **OpenAI Integration**: Function calling with structured responses
- **Extensible**: Easy to add custom tools

## Installation

```bash
# Install dependencies (requires uv or pip)
pip install -e .

# Or with uv
uv pip install -e .
```

## Quick Start

```bash
# Set your OpenAI API key
export OPENAI_API_KEY="your-api-key"

# Run the basic agent
python examples/basic_agent.py
```

## Usage

```python
from xiaomei_brain import Agent, Config, ToolRegistry, LLMClient
from xiaomei_brain.tools.base import tool

# Configure
config = Config()
llm = LLMClient(model=config.model, api_key=config.api_key)

# Create and register tools
tools = ToolRegistry()

@tool(name="my_tool", description="A custom tool")
def my_func(x: int) -> str:
    return str(x * 2)

tools.register(my_func)

# Run agent
agent = Agent(llm=llm, tools=tools)
response = agent.run("What's 5 * 2?")
print(response)
```

## Testing

```bash
pytest tests/
```

## License

MIT
