# Agent System

This document covers the core agent system in ADK, including agent types, configuration, lifecycle, and orchestration patterns. For information about running agents, see [Execution and Orchestration](/google/adk-python/4-execution-and-orchestration). For LLM integration details, see [LLM Integration](/google/adk-python/5-llm-integration). For tools used by agents, see [Tools and Extensions](/google/adk-python/6-tools-and-extensions).

## Overview

The agent system provides the fundamental abstractions for building AI agents in ADK. Agents are defined by extending `BaseAgent` or one of its specialized subclasses. Each agent can have sub-agents, tools, instructions, and callbacks that control its behavior. The system supports both text-based (`run_async`) and real-time audio/video (`run_live`) execution modes.

**Sources:** [src/google/adk/agents/base\_agent.py85-698](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L85-L698)

## Agent Type Hierarchy

Orchestration Agents

Core Agents

BaseAgent  
(base\_agent.py)

LlmAgent  
(llm\_agent.py)

SequentialAgent  
(sequential\_agent.py)

ParallelAgent  
(parallel\_agent.py)

LoopAgent  
(loop\_agent.py)

CustomAgent  
(User-defined)

**Agent Type Comparison**

Agent Type

Purpose

Key Characteristics

File Location

`BaseAgent`

Abstract base class

Defines core lifecycle methods `run_async()`, `run_live()`, callback system

[base\_agent.py85-698](https://github.com/google/adk-python/blob/223d9a7f/base_agent.py#L85-L698)

`LlmAgent`

LLM-powered agent

Model integration, tools, instructions, content generation

[llm\_agent.py183-996](https://github.com/google/adk-python/blob/223d9a7f/llm_agent.py#L183-L996)

`SequentialAgent`

Workflow orchestration

Executes sub-agents in sequence

[sequential\_agent.py47-159](https://github.com/google/adk-python/blob/223d9a7f/sequential_agent.py#L47-L159)

`ParallelAgent`

Concurrent execution

Runs sub-agents in parallel with isolated branches

[parallel\_agent.py150-217](https://github.com/google/adk-python/blob/223d9a7f/parallel_agent.py#L150-L217)

`LoopAgent`

Iterative workflows

Repeats sub-agents until exit condition or max iterations

[loop\_agent.py51-166](https://github.com/google/adk-python/blob/223d9a7f/loop_agent.py#L51-L166)

**Sources:** [src/google/adk/agents/base\_agent.py85-86](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L85-L86) [src/google/adk/agents/llm\_agent.py183-184](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L183-L184) [src/google/adk/agents/sequential\_agent.py47-48](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/sequential_agent.py#L47-L48) [src/google/adk/agents/parallel\_agent.py150-151](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/parallel_agent.py#L150-L151) [src/google/adk/agents/loop\_agent.py51-56](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/loop_agent.py#L51-L56)

## BaseAgent Architecture

Callback System

Lifecycle Methods

Agent State

\_load\_agent\_state()

BaseAgentState  
(Pydantic model)

\_create\_agent\_state\_event()

BaseAgent Core

name: str  
(unique identifier)

description: str  
(capability description)

parent\_agent: Optional\[BaseAgent\]

sub\_agents: list\[BaseAgent\]

run\_async()  
(final, calls \_run\_async\_impl)

\_run\_async\_impl()  
(override in subclasses)

run\_live()  
(final, calls \_run\_live\_impl)

\_run\_live\_impl()  
(override in subclasses)

before\_agent\_callback:  
Optional\[BeforeAgentCallback\]

after\_agent\_callback:  
Optional\[AfterAgentCallback\]

\_handle\_before\_agent\_callback()

\_handle\_after\_agent\_callback()

The `BaseAgent` class provides the foundation for all agents. Key responsibilities include:

-   **Agent Identity**: Each agent has a unique `name` (must be a valid Python identifier) and optional `description` used by parent agents to determine delegation
-   **Hierarchy Management**: `parent_agent` and `sub_agents` establish the agent tree structure
-   **Lifecycle Orchestration**: `run_async()` and `run_live()` are final methods that wrap implementation methods with callback execution
-   **Callback Hooks**: `before_agent_callback` and `after_agent_callback` allow interception of agent execution

**Sources:** [src/google/adk/agents/base\_agent.py85-268](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L85-L268) [src/google/adk/agents/base\_agent.py270-363](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L270-L363) [src/google/adk/agents/base\_agent.py431-546](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L431-L546)

## LlmAgent Components

LLM Flow

Tool Processing

Instruction Processing

Model Resolution

LlmAgent

model: Union\[str, BaseLlm\]  
(inherited from ancestors if empty)

instruction: Union\[str, InstructionProvider\]  
(dynamic with placeholder support)

static\_instruction: Optional\[types.ContentUnion\]  
(for context caching)

tools: list\[ToolUnion\]  
(functions, BaseTool, BaseToolset)

generate\_content\_config: Optional\[types.GenerateContentConfig\]

canonical\_model property  
(resolves to BaseLlm)

Inherits from parent\_agent

Falls back to \_default\_model  
(gemini-2.5-flash)

LLMRegistry.new\_llm()

canonical\_instruction()  
(returns str, bypass\_flag)

InstructionProvider callable  
(ctx: ReadonlyContext) -> str

Placeholder substitution  
(e.g. {customerId})

canonical\_tools()  
(resolves to list\[BaseTool\])

\_convert\_tool\_union\_to\_tools()

FunctionTool wrapper

Toolset.get\_tools\_with\_prefix()

\_llm\_flow property

AutoFlow  
(supports transfer)

SingleFlow  
(no transfer)

`LlmAgent` extends `BaseAgent` with LLM-specific capabilities:

### Model Configuration

The `model` field accepts either a string (model name) or a `BaseLlm` instance. Model resolution follows this priority:

1.  Explicit `model` field value
2.  Inherited from `parent_agent` (recursively up the tree)
3.  Default model via `LlmAgent._default_model` (configurable with `set_default_model()`)
4.  System default: `gemini-2.5-flash`

**Sources:** [src/google/adk/agents/llm\_agent.py192-198](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L192-L198) [src/google/adk/agents/llm\_agent.py499-532](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L499-L532)

### Instructions

Instructions guide the LLM's behavior and come in two forms:

-   **`instruction`**: Dynamic instructions that support placeholder substitution (e.g., `{variable_name}`) from session state. Can be a string or `InstructionProvider` callable
-   **`static_instruction`**: Static content sent literally without processing, primarily for context caching optimization. Accepts `types.ContentUnion` (str, Content, Part, Image, File, etc.)

When `static_instruction` is set, the behavior changes:

-   `static_instruction` → sent as system instruction at position 0
-   `instruction` → sent as user content after static content

**Sources:** [src/google/adk/agents/llm\_agent.py203-279](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L203-L279) [src/google/adk/agents/llm\_agent.py533-589](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L533-L589)

### Tools

The `tools` field accepts a heterogeneous list of `ToolUnion` types:

-   Python functions (wrapped in `FunctionTool`)
-   `BaseTool` instances
-   `BaseToolset` instances (expanded via `get_tools_with_prefix()`)

The `canonical_tools()` method resolves all tool unions to a flat list of `BaseTool` instances.

**Sources:** [src/google/adk/agents/llm\_agent.py281-282](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L281-L282) [src/google/adk/agents/llm\_agent.py591-610](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L591-L610) [src/google/adk/agents/llm\_agent.py135-181](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L135-L181)

### Transfer Control

LlmAgent supports controlled agent-to-agent transfer via:

-   **`disallow_transfer_to_parent`**: Prevents LLM from transferring back to parent (default: `False`)
-   **`disallow_transfer_to_peers`**: Prevents LLM from transferring to sibling agents (default: `False`)

When both are `True`, the agent uses `SingleFlow` instead of `AutoFlow`, which provides a simpler execution model without transfer support.

**Sources:** [src/google/adk/agents/llm\_agent.py295-305](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L295-L305) [src/google/adk/agents/llm\_agent.py695-703](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L695-L703)

### Advanced Features

-   **`output_schema`**: Enforces structured output using Pydantic models (disables tool use)
-   **`output_key`**: Stores agent output in session state for later use
-   **`planner`**: Enables step-by-step planning with `BasePlanner` implementations
-   **`code_executor`**: Allows execution of code blocks from model responses

**Sources:** [src/google/adk/agents/llm\_agent.py319-353](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L319-L353)

## Agent Execution Lifecycle

LLMLlmFlowLlmAgentPluginManagerBaseAgentRunnerLLMLlmFlowLlmAgentPluginManagerBaseAgentRunnerloop\[Until final response or transfer\]alt\[Sub-agent to resume\]\[Normal execution\]alt\[Callback returns content\]\[Continue execution\]alt\[Callback returns content\]\[No callback override\]run\_async(parent\_context)\_create\_invocation\_context()run\_before\_agent\_callback()Optional\[Content\]Event (bypass execution)canonical\_before\_agent\_callbacksEvent (bypass execution)\_run\_async\_impl(ctx)\_load\_agent\_state()run\_async(ctx)Eventsrun\_async(ctx)generate\_content()LlmResponseProcess function callsEventEvent\_create\_agent\_state\_event()Eventrun\_after\_agent\_callback()Optional\[Content\]canonical\_after\_agent\_callbacksEvent (if callback provides)

### Execution Phases

**1\. Context Creation**

Each agent invocation creates an `InvocationContext` that encapsulates:

-   Current agent reference
-   Session and state
-   Service dependencies (session, artifact, memory, credential)
-   Plugin manager
-   Invocation ID and branch

**Sources:** [src/google/adk/agents/base\_agent.py400-405](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L400-L405) [src/google/adk/agents/invocation\_context.py98-413](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/invocation_context.py#L98-L413)

**2\. Before-Agent Callbacks**

Callbacks execute in this order:

1.  Plugin `before_agent_callback()` methods
2.  Agent's `before_agent_callback` (or list of callbacks)

If any callback returns `types.Content`, agent execution is bypassed and the content is returned immediately.

**Sources:** [src/google/adk/agents/base\_agent.py431-487](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L431-L487)

**3\. Implementation Execution**

The `_run_async_impl()` or `_run_live_impl()` method yields `Event` objects. For `LlmAgent`:

-   Loads agent state for resumability
-   Checks for sub-agent to resume
-   Runs LLM flow (AutoFlow or SingleFlow)
-   Creates agent state events for resumable apps

**Sources:** [src/google/adk/agents/llm\_agent.py447-495](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L447-L495) [src/google/adk/agents/base\_agent.py333-347](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L333-L347)

**4\. After-Agent Callbacks**

Similar to before-agent callbacks:

1.  Plugin `after_agent_callback()` methods
2.  Agent's `after_agent_callback` (or list of callbacks)

If any callback returns `types.Content`, an additional event is appended to the event stream.

**Sources:** [src/google/adk/agents/base\_agent.py489-546](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L489-L546)

## Callbacks

Callback Context

LlmAgent Callbacks

Agent Callbacks

before\_agent\_callback:  
Callable\[\[CallbackContext\], Optional\[Content\]\]

after\_agent\_callback:  
Callable\[\[CallbackContext\], Optional\[Content\]\]

before\_model\_callback:  
Callable\[\[CallbackContext, LlmRequest\], Optional\[LlmResponse\]\]

after\_model\_callback:  
Callable\[\[CallbackContext, LlmResponse\], Optional\[LlmResponse\]\]

on\_model\_error\_callback:  
Callable\[\[CallbackContext, LlmRequest, Exception\], Optional\[LlmResponse\]\]

before\_tool\_callback:  
Callable\[\[BaseTool, dict, ToolContext\], Optional\[dict\]\]

after\_tool\_callback:  
Callable\[\[BaseTool, dict, ToolContext, dict\], Optional\[dict\]\]

on\_tool\_error\_callback:  
Callable\[\[BaseTool, dict, ToolContext, Exception\], Optional\[dict\]\]

CallbackContext

state property  
(read/write access)

invocation\_context property  
(read-only)

\_event\_actions  
(internal state delta)

### Callback Types

**Agent-Level Callbacks** (defined in `BaseAgent`):

-   **`before_agent_callback`**: Invoked before agent execution. Can bypass agent run by returning content.
-   **`after_agent_callback`**: Invoked after agent execution. Can append additional response.

**Model-Level Callbacks** (defined in `LlmAgent`):

-   **`before_model_callback`**: Called before each LLM request. Can modify request or bypass LLM call.
-   **`after_model_callback`**: Called after each LLM response. Can modify or replace response.
-   **`on_model_error_callback`**: Called when LLM request fails. Can provide fallback response.

**Tool-Level Callbacks** (defined in `LlmAgent`):

-   **`before_tool_callback`**: Called before tool execution. Can modify args or bypass tool call.
-   **`after_tool_callback`**: Called after tool execution. Can modify result.
-   **`on_tool_error_callback`**: Called when tool execution fails. Can provide fallback result.

**Sources:** [src/google/adk/agents/base\_agent.py136-163](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L136-L163) [src/google/adk/agents/llm\_agent.py356-444](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L356-L444)

### Callback Lists

All callback fields accept either a single callback or a list of callbacks:

```
before_agent_callback: Optional[BeforeAgentCallback]
# where BeforeAgentCallback = Union[_SingleAgentCallback, list[_SingleAgentCallback]]
```

When a list is provided, callbacks execute in order until one returns a non-None value, which short-circuits the chain.

**Sources:** [src/google/adk/agents/base\_agent.py60-68](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L60-L68) [src/google/adk/agents/llm\_agent.py68-126](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L68-L126)

### CallbackContext

The `CallbackContext` provides callbacks with:

-   **`state`**: Read/write access to session state (app, user, session scopes)
-   **`invocation_context`**: Read-only access to full invocation context
-   **Internal state tracking**: Accumulates state changes for event generation

**Sources:** [src/google/adk/agents/callback\_context.py](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/callback_context.py)

## Sequential Agent Orchestration

SequentialAgent Execution

Pause

Continue

Initialize/Resume

Load SequentialAgentState

Get start\_index from state

for i in range(start\_index, len(sub\_agents))

sub\_agents\[i\]

Create agent\_state checkpoint  
(current\_sub\_agent=name)

sub\_agent.run\_async(ctx)

Check ctx.should\_pause\_invocation()

End of sub\_agents loop

Create end\_of\_agent checkpoint

Return (pause invocation)

`SequentialAgent` executes sub-agents in order. Key features:

-   **Stateful Resumption**: Uses `SequentialAgentState` with `current_sub_agent` field to track progress
-   **Checkpointing**: Yields agent state events before each sub-agent when `is_resumable=True`
-   **Pause Support**: Respects `ctx.should_pause_invocation()` for long-running tool calls

**State Model:**

```
class SequentialAgentState(BaseAgentState):
    current_sub_agent: str = ''  # Name of current sub-agent to run
```

**Sources:** [src/google/adk/agents/sequential\_agent.py39-117](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/sequential_agent.py#L39-L117)

## Parallel Agent Orchestration

ParallelAgent Execution

Concurrent Execution

put(event)

put(event)

put(event)

asyncio.Queue  
(shared event queue)

Task: sub\_agent\_1.run\_async()

Task: sub\_agent\_2.run\_async()

Task: sub\_agent\_N.run\_async()

Initialize

Create isolated branch contexts  
for each sub-agent

Merge events from queue

Yield event

Signal task to continue

All tasks complete

Create end\_of\_agent checkpoint

`ParallelAgent` runs sub-agents concurrently with isolated conversation histories:

-   **Branch Isolation**: Each sub-agent gets a unique branch suffix (e.g., `parent.sub_agent_1`)
-   **Event Merging**: Uses `asyncio.Queue` and `asyncio.TaskGroup` (Python 3.11+) or custom implementation (Python 3.10)
-   **Backpressure**: Each task waits for upstream to process events before generating new ones
-   **Resumption**: Skips sub-agents that have `end_of_agent=True` in context

**Sources:** [src/google/adk/agents/parallel\_agent.py35-210](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/parallel_agent.py#L35-L210)

## Loop Agent Orchestration

LoopAgent Execution

Escalate

Continue

Pause

Continue

Initialize

Load LoopAgentState

Get times\_looped, start\_index

while times\_looped < max\_iterations

for i in range(start\_index, len(sub\_agents))

sub\_agents\[i\]

Create checkpoint  
(current\_sub\_agent, times\_looped)

sub\_agent.run\_async(ctx)

Check event.actions.escalate

Check ctx.should\_pause\_invocation()

times\_looped += 1

ctx.reset\_sub\_agent\_states()

Create end\_of\_agent checkpoint

Return (pause invocation)

`LoopAgent` repeats sub-agents until exit condition or `max_iterations`:

-   **Exit Conditions**:
    -   Any sub-agent yields event with `actions.escalate=True`
    -   `max_iterations` reached (if configured)
-   **State Reset**: Calls `ctx.reset_sub_agent_states()` after each loop iteration
-   **Iteration Tracking**: Uses `LoopAgentState` with `times_looped` counter

**State Model:**

```
class LoopAgentState(BaseAgentState):
    current_sub_agent: str = ''  # Name of current sub-agent to run
    times_looped: int = 0         # Number of completed iterations
```

**Sources:** [src/google/adk/agents/loop\_agent.py40-166](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/loop_agent.py#L40-L166)

## Agent Configuration

Agent Instances

Loading Process

Config Models

Configuration Sources

agent.yaml  
(YAML configuration)

agent.py  
(Python code)

AgentConfig  
(RootModel discriminated union)

BaseAgentConfig

LlmAgentConfig

SequentialAgentConfig

ParallelAgentConfig

LoopAgentConfig

yaml.safe\_load()

agent\_config\_discriminator()  
(routes by agent\_class)

model\_validate()

\_parse\_config()  
(class-specific)

Agent.**init**()

BaseAgent

LlmAgent

SequentialAgent

ParallelAgent

LoopAgent

### YAML Configuration

Agents can be defined in YAML using the `AgentConfig` schema. The `agent_class` field determines which agent type is created:

```
agent_class: LlmAgent  # or SequentialAgent, ParallelAgent, LoopAgent
name: my_agent
description: Agent description
model: gemini-2.5-flash
instruction: You are a helpful assistant.
tools:
  - name: google_search
  - name: my_library.my_tools.my_tool
sub_agents:
  - config_path: sub_agents/sub_agent.yaml
  - code: my_library.agents.custom_agent
```

**Discriminator Logic:**

The `agent_config_discriminator()` function routes configuration to the appropriate config class based on `agent_class`:

-   `"LlmAgent"` → `LlmAgentConfig`
-   `"SequentialAgent"` → `SequentialAgentConfig`
-   `"ParallelAgent"` → `ParallelAgentConfig`
-   `"LoopAgent"` → `LoopAgentConfig`
-   Custom classes → `BaseAgentConfig`

Fully qualified names (e.g., `"google.adk.agents.llm_agent.LlmAgent"`) are normalized to short names.

**Sources:** [src/google/adk/agents/agent\_config.py41-74](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/agent_config.py#L41-L74) [src/google/adk/agents/base\_agent\_config.py36-82](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent_config.py#L36-L82)

### Config Classes

Each agent type has a corresponding config class extending `BaseAgentConfig`:

Config Class

Additional Fields

Purpose

`BaseAgentConfig`

`name`, `description`, `sub_agents`, callbacks

Common fields for all agents

`LlmAgentConfig`

`model`, `instruction`, `static_instruction`, `tools`, `generate_content_config`

LLM-specific configuration

`SequentialAgentConfig`

_(inherits BaseAgentConfig)_

Sequential orchestration

`ParallelAgentConfig`

_(inherits BaseAgentConfig)_

Parallel orchestration

`LoopAgentConfig`

`max_iterations`

Loop control

**Sources:** [src/google/adk/agents/base\_agent\_config.py36-82](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent_config.py#L36-L82) [src/google/adk/agents/llm\_agent\_config.py35-231](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent_config.py#L35-L231) [src/google/adk/agents/sequential\_agent\_config.py](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/sequential_agent_config.py) [src/google/adk/agents/parallel\_agent\_config.py](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/parallel_agent_config.py) [src/google/adk/agents/loop\_agent\_config.py](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/loop_agent_config.py)

### Loading Process

The `from_config()` class method converts config objects to agent instances:

1.  **Parse Common Fields**: `__create_kwargs()` handles `name`, `description`, `sub_agents`, callbacks
2.  **Parse Class-Specific Fields**: `_parse_config()` handles agent-specific configuration
3.  **Instantiate Agent**: Calls agent constructor with merged kwargs

For sub-agents specified via `config_path` or `code`, the `resolve_agent_reference()` function loads them recursively.

**Sources:** [src/google/adk/agents/base\_agent.py620-698](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L620-L698) [src/google/adk/agents/llm\_agent.py939-993](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L939-L993)

### CodeConfig and Tool Resolution

Tools and callbacks can be specified using `CodeConfig`:

```
tools:
  - name: my_library.my_tools.MyTool  # Class reference
    args:
      - name: param1
        value: value1
  - name: my_library.my_tools.my_function  # Function reference
```

The `_resolve_tools()` method handles:

-   ADK built-in tools (e.g., `google_search`)
-   User-defined `BaseTool`/`BaseToolset` classes
-   User-defined functions
-   Tool-generating functions with arguments

**Sources:** [src/google/adk/agents/llm\_agent.py882-937](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L882-L937) [src/google/adk/agents/common\_configs.py46-82](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/common_configs.py#L46-L82)

## Agent State Management

State Operations

InvocationContext State

Agent State Types

BaseAgentState  
(empty base class)

SequentialAgentState  
\- current\_sub\_agent: str

LoopAgentState  
\- current\_sub\_agent: str  
\- times\_looped: int

Custom AgentState  
(user-defined)

agent\_states: dict\[str, dict\]  
(agent\_name -> state\_dict)

end\_of\_agents: dict\[str, bool\]  
(agent\_name -> completed)

\_load\_agent\_state()  
(deserialize from context)

ctx.set\_agent\_state()  
(update or mark end)

\_create\_agent\_state\_event()  
(persist to event stream)

populate\_invocation\_agent\_states()  
(restore from events)

### State Model

Agent state enables resumability by persisting execution progress:

-   **`BaseAgentState`**: Empty base class for type safety
-   **`SequentialAgentState`**: Tracks `current_sub_agent` name
-   **`LoopAgentState`**: Tracks `current_sub_agent` and `times_looped` counter

Custom agents can define their own state classes extending `BaseAgentState`.

**Sources:** [src/google/adk/agents/base\_agent.py73-83](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L73-L83) [src/google/adk/agents/sequential\_agent.py39-45](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/sequential_agent.py#L39-L45) [src/google/adk/agents/loop\_agent.py40-49](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/loop_agent.py#L40-L49)

### State Lifecycle

1.  **Load State**: `_load_agent_state(ctx, StateType)` deserializes state from `ctx.agent_states[agent_name]`
2.  **Update State**: `ctx.set_agent_state(name, agent_state=..., end_of_agent=...)` updates context
3.  **Persist State**: `_create_agent_state_event(ctx)` creates event with `actions.agent_state` and `actions.end_of_agent`
4.  **Restore State**: `populate_invocation_agent_states()` rebuilds state from event history

**Sources:** [src/google/adk/agents/base\_agent.py165-206](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L165-L206) [src/google/adk/agents/invocation\_context.py224-304](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/invocation_context.py#L224-L304)

### End-of-Agent Tracking

When an agent completes:

1.  Call `ctx.set_agent_state(name, end_of_agent=True)` - clears agent\_state, sets end\_of\_agents flag
2.  Yield `_create_agent_state_event(ctx)` - persists completion
3.  On resumption, orchestrators skip agents where `ctx.end_of_agents[name]=True`

**Sources:** [src/google/adk/agents/invocation\_context.py224-254](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/invocation_context.py#L224-L254)

## Instruction System

Instruction Placement

Resolution Process

Instruction Types

static\_instruction  
(types.ContentUnion)

instruction (string)  
with {placeholders}

instruction (InstructionProvider)  
callable

global\_instruction (deprecated)

canonical\_instruction()  
returns (str, bypass\_flag)

inject\_state\_to\_instruction()  
substitute {variable}

Call InstructionProvider(ctx)

canonical\_global\_instruction()

System Instruction  
(sent to LLM)

User Content  
(sent to LLM)

### Instruction Types

**Static Instructions** (`static_instruction`):

-   Sent literally without processing
-   Supports rich content: text, images, files (via `types.ContentUnion`)
-   Primarily for context caching optimization
-   Always sent as system instruction at position 0

**Dynamic String Instructions** (`instruction`):

-   Supports placeholder substitution: `{variable_name}`
-   Resolves from session state (app:, user:, session: scopes)
-   Escaping: `{{variable}}` → literal `{variable}`
-   Only valid identifiers are substituted

**Instruction Providers** (`instruction`):

-   Callable: `(ctx: ReadonlyContext) -> str` or `async (...) -> str`
-   Full programmatic control over instruction content
-   Bypasses placeholder substitution (returns `bypass_state_injection=True`)

**Sources:** [src/google/adk/agents/llm\_agent.py203-279](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L203-L279) [src/google/adk/agents/llm\_agent.py533-589](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L533-L589)

### Instruction Placement Logic

When `static_instruction` is **None**:

-   `instruction` → system\_instruction
-   No user content from instruction

When `static_instruction` is **set**:

-   `static_instruction` → system\_instruction (position 0)
-   `instruction` → user content (after static content)

This enables context caching: static content is cached, dynamic instruction changes without invalidating cache.

**Sources:** [tests/unittests/flows/llm\_flows/test\_instructions.py](https://github.com/google/adk-python/blob/223d9a7f/tests/unittests/flows/llm_flows/test_instructions.py)

### Global Instructions (Deprecated)

`global_instruction` provides instructions to all agents in the tree. Only the root agent's `global_instruction` takes effect. This field is deprecated; use `GlobalInstructionPlugin` instead.

**Sources:** [src/google/adk/agents/llm\_agent.py217-228](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L217-L228) [src/google/adk/agents/llm\_agent.py557-589](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L557-L589)

## Agent Transfer Mechanism

Execution Flow

Resume Logic

Agent Lookup

Transfer Detection

Not found

Found

Event with transfer\_to\_agent function

FunctionResponse for transfer\_to\_agent

Extract agent\_name from response

root\_agent.find\_agent(name)

Validate agent exists

Error: Agent not found

\_get\_subagent\_to\_resume()

Check last event author

Search backwards for transfer events

Last event = transfer from self

Last event = from user or other agent

Run sub\_agent.run\_async(ctx)

Set end\_of\_agent=True

Yield agent state event

### Transfer Flow

Agent transfer enables dynamic routing of conversation control:

1.  **LLM Decision**: Model calls `transfer_to_agent` function with `agent_name` parameter
2.  **Function Execution**: Framework executes transfer (no user-visible effect)
3.  **Target Lookup**: `find_agent(agent_name)` searches agent tree from root
4.  **Resume Detection**: `_get_subagent_to_resume()` determines which agent should run next
5.  **Context Switching**: Target agent's `run_async()` is invoked with same context

**Sources:** [src/google/adk/agents/llm\_agent.py705-805](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L705-L805)

### Transfer Rules

Transfer behavior depends on `disallow_transfer_to_parent` and `disallow_transfer_to_peers`:

Configuration

Behavior

Use Case

Both `False` (default)

Can transfer to parent and peers

Multi-agent collaboration

`disallow_transfer_to_parent=True`

Cannot transfer back to parent

Task completion handoff

`disallow_transfer_to_peers=True`

Cannot transfer to siblings

Hierarchical delegation

Both `True`

No transfers (SingleFlow)

Standalone agent

**Note:** Setting `disallow_transfer_to_parent=True` also prevents the agent from continuing to reply, forcing transfer back to parent in the next turn to avoid one-way transfer traps.

**Sources:** [src/google/adk/agents/llm\_agent.py295-305](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L295-L305)

### Resume Logic

The `_get_subagent_to_resume()` method handles two cases:

**Case 1:** Last event is from current agent with transfer

-   Return the agent specified in the transfer response

**Case 2:** Last event is from user or another agent

-   If user is responding to another agent's tool call, no sub-agent to resume (current agent continues)
-   Otherwise, search backwards for last transfer from current agent

**Sources:** [src/google/adk/agents/llm\_agent.py705-748](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/llm_agent.py#L705-L748)

## Agent Hierarchy and Discovery

Validation

Navigation Methods

Agent Tree

root\_agent

sub\_agent\_1

sub\_agent\_2

sub\_agent\_1\_1

sub\_agent\_1\_2

agent.parent\_agent  
(set by parent)

agent.root\_agent  
(traverse to top)

agent.find\_agent(name)  
(search self + descendants)

agent.find\_sub\_agent(name)  
(search descendants only)

Name must be valid identifier  
(cannot be 'user')

Sub-agents must have unique names  
(warning only)

Agent can only have one parent

### Hierarchy Management

**Parent-Child Relationships:**

-   `parent_agent` is automatically set when agent is added to `sub_agents` list
-   An agent can only have one parent
-   Attempting to add agent with existing parent raises `ValueError`

**Tree Traversal:**

-   `root_agent` property traverses up to find the root
-   `find_agent(name)` searches self and all descendants
-   `find_sub_agent(name)` searches only descendants

**Sources:** [src/google/adk/agents/base\_agent.py124-134](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L124-L134) [src/google/adk/agents/base\_agent.py365-399](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L365-L399) [src/google/adk/agents/base\_agent.py608-617](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L608-L617)

### Name Validation

Agent names must:

-   Be valid Python identifiers (alphanumeric and underscore, cannot start with digit)
-   Not be "user" (reserved for end-user input)
-   Be unique among siblings (warning issued if duplicates found)

**Sources:** [src/google/adk/agents/base\_agent.py552-606](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L552-L606)

### Agent Cloning

The `clone()` method creates a deep copy of an agent:

-   All fields are copied (shallow copy for lists)
-   Sub-agents are recursively cloned
-   Parent-child relationships are re-established
-   Original `parent_agent` is cleared on clone

This is useful for reusing agent configurations with different parameters.

**Sources:** [src/google/adk/agents/base\_agent.py208-268](https://github.com/google/adk-python/blob/223d9a7f/src/google/adk/agents/base_agent.py#L208-L268)
