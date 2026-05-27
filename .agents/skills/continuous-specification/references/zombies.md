# ZOMBIES - Specification Discovery Heuristic

## Structure

**ZOM axis** (simple → complex):
- **Z** - Zero: initial state after creation (empty, not full, default values)
- **O** - One: first item, first transition
- **M** - Many: multiple items, more complex scenarios

**BIE considerations** (apply at each ZOM level):
- **B** - Boundary: transitions between states, both directions (empty↔not-empty, not-full↔full)
- **I** - Interface: let specifications reveal what methods, parameters, and return types are needed
- **E** - Exceptions: error conditions, and verify the object still works after errors

**S** - Simple scenarios, simple solutions (applies throughout)

## Key principles

**Specify transitions, not just states.** Verify moving from empty to not-empty, and back again.

**Procrastinate deliberately.** Defer implementation until specifications demand it. Hard-coded return values are fine — specs will catch if you forget to generalize.

**Interface emerges from specifications.** Don't design the API upfront. Write specs, and the needed methods reveal themselves.

**Exceptions come last.** Get happy paths working first, then specify error conditions. Verify that failed operations don't corrupt the object.

## Example: Circular buffer (FIFO)

```
[SPEC] New buffer is empty                               <- Z
[SPEC] New buffer is not full                            <- Z
[SPEC] Put one item, buffer is not empty                 <- O
[SPEC] Put then get returns the item                     <- O + I
[SPEC] Put then get, buffer is empty again               <- O + B (transition back)
[SPEC] Put three items, get returns them in order        <- M
[SPEC] Fill to capacity, buffer is full                  <- M + B
[SPEC] Wrap around: fill, empty, refill works            <- M + B
[SPEC] Put to full buffer fails                          <- E
[SPEC] Get from empty buffer fails                       <- E
[SPEC] After failed put, buffer still works              <- E (integrity check)
```

---
Source: [TDD Guided by ZOMBIES](https://blog.wingman-sw.com/tdd-guided-by-zombies) by James Grenning
