# 🛡️ WORKFLOW GUARD - Jutsu-Labs Agent Architecture Enforcement

## ⛔ MANDATORY READING: Session Start

**This file MUST be read at the start of EVERY session before any work on Jutsu-Labs.**

---

## 🔴 The Rule (No Exceptions)

**ALL Jutsu-Labs code modifications MUST go through `/orchestrate`**

### What This Means

No exceptions. Not for:
- ❌ "Simple" bug fixes
- ❌ "Quick" one-line changes
- ❌ "Obvious" typo corrections
- ❌ Test updates
- ❌ Documentation changes to code
- ❌ "I already know the fix"

**EVERYTHING uses `/orchestrate`.**

---

## 💡 Why This Architecture Exists

### The Problem

You (Claude Code) have a natural tendency to:
1. ✅ See a problem → ❌ Immediately solve it directly
2. ✅ Have tools available (Edit/Write/MultiEdit) → ❌ Use them without routing
3. ✅ Feel capable and knowledgeable → ❌ Skip agent context loading
4. ✅ Want to be efficient → ❌ Bypass "unnecessary" steps

**This is WRONG for Jutsu-Labs.**

### Why It Matters

When you bypass the agent architecture:

1. **Context Loss**: Agent context files contain module-specific knowledge you don't have loaded
2. **Architecture Violations**: Dependency rules and boundaries go unenforced
3. **Knowledge Gaps**: Fixes don't accumulate in Serena memories for future sessions
4. **Validation Failures**: Multi-level validation chains are broken
5. **Pattern Inconsistency**: Established module patterns are ignored
6. **Bug Recurrence**: Same issues recur because solutions aren't documented properly

### What Agents Know That You Don't (In Immediate Context)

Each agent's `.md` file contains:
- **Module Ownership**: Exact files and responsibilities
- **Known Issues**: Past problems and their solutions
- **Dependency Rules**: What can/cannot be imported
- **Performance Targets**: Required benchmarks and optimizations
- **Testing Requirements**: Coverage targets and test patterns
- **Established Patterns**: Module-specific conventions
- **Integration Points**: How module connects to others

---

## ✅ Pre-Flight Checklist

**Before ANY work on Jutsu-Labs, verify:**

### Session Initialization
- [ ] Have I read WORKFLOW_GUARD.md this session?
- [ ] Have I acknowledged the mandatory workflow?
- [ ] Do I understand WHY this architecture exists?

### Task Received
- [ ] Has the user given me a task?
- [ ] Have I formulated the `/orchestrate` command?
- [ ] Am I clear on what needs to be done?

### Temptation Check (CRITICAL)
- [ ] Am I tempted to use Edit/Write/MultiEdit directly? → ⛔ STOP
- [ ] Am I thinking "this is too simple for orchestration"? → ⛔ WRONG
- [ ] Am I thinking "I'll just quickly fix this"? → ⛔ WRONG
- [ ] Am I thinking "orchestration is overkill"? → ⛔ WRONG

### Correct Path
- [ ] Am I about to execute `/orchestrate <description>`? → ✅ PROCEED

---

## 🚨 Red Flags (STOP Immediately If You Think This)

| Thought | Why It's Wrong | Correct Action |
|---------|----------------|----------------|
| "This is simple, I'll just fix it quickly" | Agents have context you don't | Use `/orchestrate` |
| "I have Read/Edit access, I can handle this" | Architecture boundaries must be enforced | Use `/orchestrate` |
| "Orchestration is overkill for a typo" | Even typos benefit from validation | Use `/orchestrate` |
| "I already know the fix from docs" | Agents know project-specific patterns | Use `/orchestrate` |
| "This will be faster if I do it directly" | Speed ≠ Quality, context matters | Use `/orchestrate` |
| "The agent will just do what I would do anyway" | Agents have loaded context you don't | Use `/orchestrate` |

---

## ✅ Green Light Indicators (Proceed With Confidence)

| Situation | Correct Response | Outcome |
|-----------|------------------|---------|
| User: "Fix bug in Schwab API" | `/orchestrate fix bug in Schwab API` | Agent reads context, applies fix |
| User: "Add logging to EventLoop" | `/orchestrate add logging to EventLoop` | Agent knows logging patterns |
| User: "Update tests for Portfolio" | `/orchestrate update tests for Portfolio` | Agent knows test structure |
| User: "Refactor DataSync" | `/orchestrate refactor DataSync` | Agent applies module patterns |

---

## 🔄 Enforcement Mechanism

This file serves as:

### 1. Preventive Control (Before Work)
- Read at session start
- Explicit acknowledgment required
- Mental model establishment

### 2. Reference Guide (During Work)
- Checklist when tempted to bypass
- Red flag recognition
- Correct path reinforcement

### 3. Validation Tool (After Work)
- Post-work review
- Compliance verification
- Pattern reinforcement

---

## 📋 Required Acknowledgment

**At the start of EVERY session, you must state:**

> "I have read WORKFLOW_GUARD.md. I understand that ALL Jutsu-Labs work MUST use `/orchestrate`. I will not use Edit/Write/MultiEdit directly on any Jutsu-Labs code files."

---

## 🎯 Success Criteria

### You're Doing It Right When:
- ✅ Every task starts with `/orchestrate`
- ✅ You never use Edit/Write/MultiEdit directly on code
- ✅ You refer to this file when tempted to bypass
- ✅ You understand WHY the architecture exists

### You're Doing It Wrong When:
- ❌ You make "quick fixes" without orchestration
- ❌ You think "this is too simple for the architecture"
- ❌ You use direct tool access "just this once"
- ❌ You justify bypassing for efficiency

---

## 📊 Metrics for Compliance

Track over time (via `/validate-workflow`):
- **Orchestration Usage**: Should be 100%
- **Direct Tool Bypasses**: Should be 0
- **Agent Context Reads**: Should match task count
- **Serena Memory Writes**: Should match task count
- **CHANGELOG.md Updates**: Should match task count

---

## 🔧 Tools Available (And When to Use Them)

| Tool | Allowed Direct Use? | When to Use | Notes |
|------|---------------------|-------------|-------|
| `/orchestrate` | ✅ ALWAYS | ALL code modifications | Primary command |
| `Read` | ✅ YES | Reading files for context | Information gathering only |
| `Grep` | ✅ YES | Searching for patterns | Information gathering only |
| `Glob` | ✅ YES | Finding files | Information gathering only |
| `Bash` | ✅ YES | Running tests, git commands | Non-modifying operations |
| `Edit` | ❌ NO | — | ONLY via `/orchestrate` |
| `Write` | ❌ NO | — | ONLY via `/orchestrate` |
| `MultiEdit` | ❌ NO | — | ONLY via `/orchestrate` |

---

## 🎓 Understanding the Architecture

### The Flow (How It Should Work)

```
User Request
    ↓
Read WORKFLOW_GUARD.md (if session start)
    ↓
Acknowledge mandatory workflow
    ↓
Formulate: /orchestrate <task description>
    ↓
Execute /orchestrate command
    ↓
System routes to appropriate orchestrator
    ↓
Orchestrator delegates to specific agent
    ↓
Agent reads its context file (.claude/layers/.../modules/*_AGENT.md)
    ↓
Agent has full context: ownership, patterns, constraints, history
    ↓
Agent applies expertise and makes changes
    ↓
Agent validates at module level
    ↓
Orchestrator validates at layer level
    ↓
System validates at system level
    ↓
CHANGELOG.md updated automatically
    ↓
Serena memory written automatically
    ↓
Report results to user
```

### What You Bypass When You Skip This

When you use Edit/Write directly, you skip:
- ❌ Agent context loading
- ❌ Module-specific pattern application
- ❌ Architecture boundary enforcement
- ❌ Multi-level validation
- ❌ Automatic documentation
- ❌ Knowledge accumulation
- ❌ Dependency checking
- ❌ Performance target validation

---

## 🔐 Final Reminder

**The agent architecture is not optional. It's not a suggestion. It's not "nice to have."**

**It's mandatory because:**
1. Agents have context you don't
2. Architecture must be enforced
3. Knowledge must accumulate
4. Quality must be validated
5. Patterns must be consistent

**Every time you bypass it, you:**
- Lose context for future work
- Break validation chains
- Create technical debt
- Introduce inconsistencies
- Make the same mistakes again

---

## 📞 Questions?

**Q: What if the task is really simple?**
A: Simple tasks still benefit from agent context and validation. Use `/orchestrate`.

**Q: What if I'm just reading code?**
A: Read/Grep/Glob are fine for reading. Edit/Write/MultiEdit are not.

**Q: What if I'm in a hurry?**
A: Rushing creates technical debt. Do it right the first time with `/orchestrate`.

**Q: What if the agent will just do what I would do?**
A: The agent has loaded context you don't. Trust the architecture.

**Q: What if I forget?**
A: Read this file at every session start. Check the pre-flight checklist.

---

**Remember: `/orchestrate` for EVERYTHING. No exceptions. Ever.**

