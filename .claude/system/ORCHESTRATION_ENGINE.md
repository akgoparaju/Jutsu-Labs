# Orchestration Engine

**Version**: 1.0.0
**Type**: Autonomous Multi-Agent Orchestration System
**MCP Integration**: Full SuperClaude MCP support
**Documentation**: Automatic CHANGELOG.md updates

## Architecture

### Hierarchical Structure

```
LEVEL 0: SYSTEM_ORCHESTRATOR (System-wide coordination)
  ├─ Cross-Cutting: LOGGING_ORCHESTRATOR
  ├─ Cross-Cutting: VALIDATION_ORCHESTRATOR
  └─ Cross-Cutting: DOCUMENTATION_ORCHESTRATOR ← NEW!

LEVEL 1: LAYER_ORCHESTRATORS (Layer coordination)
  ├─ CORE_ORCHESTRATOR (Core Domain)
  ├─ APPLICATION_ORCHESTRATOR (Use Cases)
  └─ INFRASTRUCTURE_ORCHESTRATOR (Technical Services)

LEVEL 2: MODULE_AGENTS (Module implementation specs)
  ├─ Core: Events, EventLoop, Portfolio, Strategy
  ├─ Application: BacktestRunner, DataSync
  └─ Infrastructure: DatabaseHandler, SchwabFetcher, Indicators, Performance

LEVEL 3: TASK_AGENTS (Autonomous implementation workers)
  └─ Spawned with subagent_type: "general-purpose" (FULL MCP access)
```

### Orchestrator Role (Claude Code)

**I** (Claude Code) am the orchestrator at ALL levels:
- Read hierarchical agent specs (.claude/)
- Analyze dependencies and create waves
- Spawn Task agents with full MCP access
- Coordinate validation and integration
- Update documentation via DOCUMENTATION_ORCHESTRATOR
- **I do NOT delegate orchestration** - only implementation

**Task agents**:
- Implement modules autonomously
- Have full MCP access (Context7, Sequential, Serena)
- Return results to orchestrator
- Do NOT orchestrate other agents

## MCP Integration

### Orchestrator Level (Claude Code - Me)

Every orchestration uses FULL SuperClaude MCP:

#### TodoWrite
```python
# Track orchestration progress
TodoWrite([
  "Implement Core layer (Events, EventLoop, Portfolio, Strategy)",
  "Implement Application layer (BacktestRunner, DataSync)",
  "Implement Infrastructure layer",
  "System integration and validation"
])

# Update throughout
TodoWrite: Mark "Implement Core layer" as completed ✅
```

#### Sequential MCP
```python
# Task decomposition
Sequential("""
Analyze task: "implement system"

Determine:
1. Scope: All layers (Core, Application, Infrastructure, Entry Points)
2. Dependencies: Core → Application → Infrastructure → Entry Points
3. Module dependencies within each layer
4. Estimated time and complexity
""")

# Debugging analysis
Sequential("""
Analyze bug from logs/error.log:
1. Parse error messages
2. Identify affected modules
3. Determine root cause
4. Propose fix strategy
""")
```

#### Context7 MCP
```python
# Look up patterns when needed
Context7("Get SQLAlchemy best practices for DatabaseHandler")
Context7("Python async patterns for EventLoop")
Context7("Decimal precision patterns for financial calculations")
```

#### Serena MCP
```python
# Checkpoint/resume
write_memory("orchestration_checkpoint", {
  "task": "implement system",
  "current_layer": "core",
  "completed_layers": [],
  "layer_status": {
    "core": {
      "status": "in_progress",
      "completed_modules": ["events", "eventloop"],
      "in_progress_modules": [],
      "pending_modules": ["portfolio", "strategy"]
    }
  },
  "start_time": "2025-01-15T10:00:00Z"
})

# Resume
checkpoint = read_memory("orchestration_checkpoint")
```

#### Morphllm MCP
```python
# Large-scale analysis (when needed)
Morphllm("Analyze all Python files for deprecated pattern XYZ")
```

### Task Agent Level

All Task agents spawned with **full MCP access**:

```python
Task("Implement Portfolio Module", {
  subagent_type: "general-purpose",  # ← Gives ALL MCP servers!
  prompt: """
  You are implementing the Portfolio module for Jutsu Labs backtesting engine.

  🎁 YOU HAVE FULL MCP ACCESS:
  ✅ Context7: Look up SQLAlchemy patterns, Python best practices
  ✅ Sequential: Use for complex logic analysis
  ✅ Serena: Read project context/memories if relevant
  ✅ All tools: Read, Write, Edit, Grep, Bash

  SPECIFICATION:
  {Read from PORTFOLIO_AGENT.md}

  DELIVERABLES:
  - jutsu_engine/core/portfolio.py
  - tests/unit/core/test_portfolio.py
  - >80% test coverage
  - All tests passing
  - Performance: <0.1ms per order

  Return: Status + file list + test results + performance metrics
  """
})
```

## Task Type Detection

### Auto-Detection Algorithm

```python
def detect_task_type(description: str) -> TaskType:
    """
    Detect task type from user description.

    Returns: implement | debug | refactor | analyze | optimize
    """
    keywords = {
        'implement': ['implement', 'create', 'build', 'add', 'layer/', 'module/', 'system'],
        'debug': ['bug', 'error', 'fix', 'broken', 'debug', 'investigate', 'logs/'],
        'refactor': ['refactor', 'improve', 'cleanup', 'restructure'],
        'analyze': ['analyze', 'review', 'audit', 'assess', 'check'],
        'optimize': ['optimize', 'performance', 'speed', 'faster', 'efficiency']
    }

    description_lower = description.lower()

    for task_type, words in keywords.items():
        if any(word in description_lower for word in words):
            return task_type

    return 'general'
```

### Task Type Workflows

#### Implementation Workflow
```python
def implementation_workflow(description):
    # 1. Use TodoWrite
    TodoWrite([f"Implement: {description}"])

    # 2. Use Sequential for planning
    plan = Sequential(f"Analyze implementation task: {description}")

    # 3. Identify scope
    scope = identify_scope(description)  # system | layer | module

    # 4. Read hierarchical specs
    if scope == 'system':
        layers = ['core', 'application', 'infrastructure', 'entry_points']
    elif scope.startswith('layer/'):
        layers = [scope.split('/')[1]]
    elif scope.startswith('module/'):
        # Single module implementation
        module = scope.split('/')[1]
        return implement_single_module(module)

    # 5. Execute layer by layer (dependency order)
    for layer in layers:
        execute_layer(layer)

    # 6. System integration
    integrate_system()

    # 7. Update documentation
    update_documentation_after_implementation()

    return success_report()
```

#### Debugging Workflow
```python
def debugging_workflow(description):
    # 1. TodoWrite
    TodoWrite([
      "Analyze error logs",
      "Identify root cause",
      "Create fix",
      "Validate fix",
      "Update CHANGELOG"
    ])

    # 2. Extract log file path
    log_path = extract_log_path(description)  # e.g., "logs/error.log"

    # 3. Read logs
    log_content = Read(log_path)

    # 4. Identify affected modules
    affected = identify_affected_modules(log_content)

    # 5. Read module specs
    specs = [Read(f".claude/layers/{layer}/modules/{module}_AGENT.md")
             for module in affected]

    # 6. Spawn analyzer agent
    diagnosis = Task("Analyze Bug", {
      subagent_type: "general-purpose",
      prompt: f"""
      Debug issue using logs/error.log.

      MCP Tools:
      - Sequential: Systematic root cause analysis
      - Context7: Debugging patterns
      - Serena: Check similar bugs

      Module specs: {specs}
      Log content: {log_content}

      Return: Root cause + fix recommendation
      """
    })

    # 7. Spawn fix agent
    fix_result = Task("Fix Bug", {
      subagent_type: "general-purpose",
      prompt: f"""
      Fix bug based on diagnosis:
      {diagnosis}

      Use Edit tool to fix code.
      Ensure all tests pass.
      """
    })

    # 8. Update CHANGELOG
    update_changelog_for_bug_fix(affected, diagnosis, fix_result)

    return success_report()
```

## Hierarchical Execution Algorithm

### Complete Orchestration Flow

```python
def orchestrate(task_description):
    """
    Main orchestration algorithm with full MCP integration.
    """

    # ═══════════════════════════════════════════════════
    # PHASE 1: INITIALIZATION
    # ═══════════════════════════════════════════════════

    # 1.1 TodoWrite: Create top-level tracking
    TodoWrite([f"Orchestrate: {task_description}"])

    # 1.2 Sequential: Analyze task
    task_analysis = Sequential(f"""
    Analyze task: "{task_description}"

    Determine:
    1. Task type: implement|debug|refactor|analyze|optimize
    2. Scope: system|layer|module|custom
    3. Affected modules/layers
    4. Dependencies
    5. Estimated complexity and time
    """)

    task_type = task_analysis.task_type
    scope = task_analysis.scope

    # 1.3 Serena: Write checkpoint
    write_memory("orchestration_start", {
      "task": task_description,
      "type": task_type,
      "scope": scope,
      "start_time": datetime.now()
    })

    # ═══════════════════════════════════════════════════
    # PHASE 2: ROUTE TO APPROPRIATE WORKFLOW
    # ═══════════════════════════════════════════════════

    if task_type == 'implement':
        return implementation_hierarchical_workflow(scope, task_analysis)
    elif task_type == 'debug':
        return debugging_workflow(task_description, task_analysis)
    elif task_type == 'refactor':
        return refactoring_workflow(scope, task_analysis)
    elif task_type == 'analyze':
        return analysis_workflow(scope, task_analysis)
    elif task_type == 'optimize':
        return optimization_workflow(scope, task_analysis)
    else:
        return general_workflow(task_description)


def implementation_hierarchical_workflow(scope, analysis):
    """
    Hierarchical implementation workflow.
    """

    # ═══════════════════════════════════════════════════
    # STEP 1: SYSTEM-LEVEL PLANNING
    # ═══════════════════════════════════════════════════

    # Read SYSTEM_ORCHESTRATOR
    system_spec = Read(".claude/system/SYSTEM_ORCHESTRATOR.md")

    # Determine layers needed
    if scope == 'system':
        layers = ['core', 'application', 'infrastructure', 'entry_points']
    elif scope.startswith('layer/'):
        layers = [scope.split('/')[1]]
    elif scope.startswith('module/'):
        # Single module - skip to module implementation
        return implement_single_module(scope.split('/')[1])

    # Update TodoWrite with layers
    TodoWrite([f"Implement layer: {layer}" for layer in layers])

    # ═══════════════════════════════════════════════════
    # STEP 2: LAYER-BY-LAYER EXECUTION
    # ═══════════════════════════════════════════════════

    layer_results = {}

    for layer in layers:
        # 2.1 Read layer orchestrator
        layer_spec = Read(f".claude/layers/{layer}/{layer.upper()}_ORCHESTRATOR.md")

        # 2.2 Identify modules in layer
        modules = extract_modules_from_spec(layer_spec)

        # 2.3 Read all module agent specs
        module_specs = {}
        for module in modules:
            spec_path = f".claude/layers/{layer}/modules/{module.upper()}_AGENT.md"
            module_specs[module] = Read(spec_path)

        # 2.4 Analyze module dependencies
        dependencies = analyze_module_dependencies(module_specs)

        # 2.5 Create dependency waves
        waves = create_dependency_waves(dependencies)
        # e.g., Wave 1: [Events], Wave 2: [EventLoop, Portfolio, Strategy]

        # 2.6 Execute waves sequentially
        module_results = {}

        for wave in waves:
            wave_results = {}

            # Spawn all modules in wave (PARALLEL)
            for module in wave.modules:
                prompt = create_module_implementation_prompt(
                  module,
                  module_specs[module],
                  layer
                )

                result = Task(f"Implement {module}", {
                  subagent_type: "general-purpose",  # Full MCP access!
                  prompt: prompt
                })

                wave_results[module] = result

                # Update TodoWrite
                TodoWrite: Mark f"{module} module" as completed

                # Serena checkpoint
                write_memory(f"module_{layer}_{module}", result)

            # Error handling for wave
            failed = [m for m, r in wave_results.items() if r.failed]
            if failed:
                retry_results = retry_modules(failed, module_specs)
                if still_failed(retry_results):
                    return error_report(layer, failed, retry_results)

            module_results.update(wave_results)

        # 2.7 Layer-level validation
        validation_result = validate_layer(layer, module_results)

        if validation_result.has_issues:
            fix_results = fix_validation_issues(validation_result.issues)
            validation_result = validate_layer(layer, module_results)

        layer_results[layer] = {
          "modules": module_results,
          "validation": validation_result
        }

        # Serena checkpoint
        write_memory(f"layer_{layer}_complete", layer_results[layer])

    # ═══════════════════════════════════════════════════
    # STEP 3: SYSTEM-LEVEL INTEGRATION
    # ═══════════════════════════════════════════════════

    integration_result = Task("System Integration", {
      subagent_type: "general-purpose",
      prompt: """
      Create integration layer for all implemented modules.

      Tasks:
      1. Create integration tests (tests/integration/)
      2. Create usage examples (scripts/)
      3. Run full test suite
      4. Generate coverage report

      Return: Test results + coverage metrics
      """
    })

    # ═══════════════════════════════════════════════════
    # STEP 4: DOCUMENTATION UPDATE
    # ═══════════════════════════════════════════════════

    doc_result = update_documentation_after_implementation(
      layers=layers,
      layer_results=layer_results,
      integration=integration_result
    )

    # ═══════════════════════════════════════════════════
    # STEP 5: FINAL REPORT
    # ═══════════════════════════════════════════════════

    return generate_hierarchical_report({
      "layers": layer_results,
      "integration": integration_result,
      "documentation": doc_result
    })
```

## Documentation Integration

### CHANGELOG.md Update Protocol

After EVERY operation, call DOCUMENTATION_ORCHESTRATOR:

```python
def update_documentation_after_implementation(layers, layer_results, integration):
    """
    Update CHANGELOG.md and other docs after implementation.
    """

    # Prepare changelog entries
    changelog_entries = []

    for layer, results in layer_results.items():
        for module, result in results['modules'].items():
            entry = {
              "module": module,
              "summary": result.summary,
              "features": result.features,
              "performance": result.performance,
              "tests": result.tests,
              "files": result.files
            }
            changelog_entries.append(entry)

    # Update CHANGELOG.md
    update_changelog(
      section="Added",
      entries=changelog_entries,
      version="Unreleased"
    )

    # Update README if major feature
    if len(layers) > 1:  # Multi-layer = major feature
        update_readme_features(layers, layer_results)

    # Update SYSTEM_DESIGN if architecture changed
    if architecture_changed(layer_results):
        update_system_design(layers, changes)

    return {
      "changelog": "Updated",
      "readme": "Updated" if len(layers) > 1 else "No change",
      "system_design": "Updated" if architecture_changed else "No change"
    }


def update_changelog_for_bug_fix(modules, diagnosis, fix_result):
    """
    Update CHANGELOG.md after bug fix.
    """

    for module in modules:
        entry = f"""
### Fixed
- **{module} Module**: Fixed {diagnosis.summary}
  - Root cause: {diagnosis.root_cause}
  - Resolution: {fix_result.resolution}
  - Affected files: {fix_result.files}
  - Performance impact: {fix_result.performance_improvement}
"""

        update_changelog(
          section="Fixed",
          entries=[entry],
          version="Unreleased"
        )
```

### CHANGELOG.md Format

Following "Keep a Changelog" standard:

```markdown
## [Unreleased]

### Added
- **Module Name**: Brief description
  - Feature 1
  - Feature 2
  - Performance: <target> ✅
  - Test coverage: X% ✅

### Changed
- **Module Name**: What changed
  - Change 1
  - Change 2
  - Performance improvement: X%

### Fixed
- **Module Name**: What was fixed
  - Root cause: Description
  - Resolution: How it was fixed
  - Affected: Files list
```

## Dependency Analysis

### Module Dependency Detection

```python
def analyze_module_dependencies(module_specs):
    """
    Analyze dependencies between modules.

    Returns: Dict[module_name, List[dependency_names]]
    """

    dependencies = {}

    for module, spec in module_specs.items():
        # Parse spec for "Depends On" section
        deps = parse_dependencies_from_spec(spec)

        # Within same layer, only track module dependencies
        # (Not cross-layer dependencies - those are handled by layer order)
        dependencies[module] = deps

    return dependencies


def create_dependency_waves(dependencies):
    """
    Create dependency-aware execution waves.

    Wave 1: Modules with no dependencies
    Wave 2: Modules depending only on Wave 1
    etc.

    Returns: List[Wave]
    """

    waves = []
    remaining = set(dependencies.keys())
    completed = set()

    while remaining:
        # Find modules with all dependencies met
        wave_modules = []
        for module in remaining:
            if all(dep in completed for dep in dependencies[module]):
                wave_modules.append(module)

        if not wave_modules:
            raise CircularDependencyError(remaining)

        waves.append(Wave(modules=wave_modules))
        completed.update(wave_modules)
        remaining -= set(wave_modules)

    return waves
```

## Validation Integration

### Multi-Level Validation

```python
def validate_layer(layer, module_results):
    """
    Validate entire layer after implementation.
    """

    validation_prompt = create_layer_validation_prompt(layer, module_results)

    validation_result = Task("Validate Layer", {
      subagent_type: "general-purpose",
      prompt: validation_prompt
    })

    return validation_result


def fix_validation_issues(issues):
    """
    Spawn fix agents for each validation issue.
    """

    fix_results = {}

    for issue in issues:
        fix_prompt = f"""
        Fix validation issue in {issue.module}:

        Issue: {issue.description}
        Type: {issue.type}
        File: {issue.file}

        Suggestion: {issue.fix_suggestion}

        Fix the code and return status.
        """

        result = Task(f"Fix {issue.module}", {
          subagent_type: "general-purpose",
          prompt: fix_prompt
        })

        fix_results[issue.module] = result

    return fix_results
```

## Checkpoint & Resume

### Checkpoint Format

```python
checkpoint = {
  "task": "implement system",
  "task_type": "implementation",
  "scope": "system",
  "start_time": "2025-01-15T10:00:00Z",
  "current_phase": "layer_execution",
  "completed_layers": ["core"],
  "current_layer": "application",
  "layer_status": {
    "core": {
      "status": "completed",
      "modules": {
        "events": {"status": "completed", "tests": "23/23"},
        "eventloop": {"status": "completed", "tests": "18/18"},
        "portfolio": {"status": "completed", "tests": "27/27"},
        "strategy": {"status": "completed", "tests": "15/15"}
      }
    },
    "application": {
      "status": "in_progress",
      "modules": {
        "backtest_runner": {"status": "completed", "tests": "15/15"},
        "data_sync": {"status": "in_progress", "tests": "0/0"}
      }
    }
  }
}
```

### Resume Algorithm

```python
def resume_orchestration():
    """
    Resume from Serena checkpoint.
    """

    # Read checkpoint
    checkpoint = read_memory("orchestration_checkpoint")

    if not checkpoint:
        return "No orchestration in progress"

    # Determine where to resume
    current_layer = checkpoint["current_layer"]
    layer_status = checkpoint["layer_status"][current_layer]

    # Find incomplete modules
    incomplete = [
      m for m, s in layer_status["modules"].items()
      if s["status"] != "completed"
    ]

    # Resume from incomplete modules
    for module in incomplete:
        implement_module(current_layer, module)

    # Continue with remaining layers
    remaining_layers = get_remaining_layers(checkpoint)
    for layer in remaining_layers:
        execute_layer(layer)

    return success_report()
```

## Error Handling

### Retry Logic

```python
def retry_modules(failed_modules, module_specs, max_retries=1):
    """
    Retry failed modules with enhanced prompts.
    """

    retry_results = {}

    for module in failed_modules:
        for attempt in range(max_retries):
            enhanced_prompt = create_module_implementation_prompt(
              module,
              module_specs[module],
              layer,
              previous_error=failed_modules[module].error
            )

            result = Task(f"Retry {module}", {
              subagent_type: "general-purpose",
              prompt: enhanced_prompt
            })

            if result.success:
                retry_results[module] = result
                break
        else:
            retry_results[module] = result  # Still failed

    return retry_results
```

## Performance Targets

```yaml
orchestration_overhead:
  planning: "< 500ms"
  per_module: "< 100ms overhead"
  per_layer: "< 200ms overhead"
  checkpoint: "< 50ms"
  documentation_update: "< 200ms"

parallel_efficiency:
  modules_per_wave: "2-4 concurrent"
  wave_overhead: "< 100ms"
  task_agent_spawn: "< 50ms per agent"
```

## Summary

The Orchestration Engine is a hierarchical autonomous system that:

1. **Detects task type** automatically (implement, debug, refactor, analyze, optimize)
2. **Uses full MCP integration** at orchestrator and Task agent levels
3. **Reads hierarchical agent structure** from `.claude/` directory
4. **Executes in dependency-aware waves** with parallel execution
5. **Validates at multiple levels** (module, layer, system)
6. **Updates CHANGELOG.md automatically** after every operation
7. **Checkpoints progress** using Serena MCP for resume capability
8. **Handles errors** with retry logic and graceful degradation

**One command → Complete autonomous execution → Production-ready code with tests and docs**
