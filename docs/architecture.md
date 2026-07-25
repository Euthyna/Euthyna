# Architecture v0.3

Two diagrams carry the design. Full-size: click through to the SVG files.

## The hourglass

Control plane above (decides, never executes), a narrow versioned protocol
waist, and a data plane below (executes, never decides) with three integration
rings: wire tap · protocol adapters · harness executors. Four launch actuators
(WHO / HOW-HARD / HOW-MANY / HOW-LONG) in a closed, evidence-gated registry;
the Serving-B slot reads traces but is never load-bearing.

![Architecture v0.3 hourglass diagram](architecture-v0.3.svg)

## Interaction flows and the scheduling boundary

The two operating modes as sequences — SIDECAR (the host owns the loop; Euthyna
observes, fixes leaks, advises) and HARNESS (Euthyna owns the loop:
calibrate / experiment) — plus the who-decides-what boundary table and the
per-runtime integration matrix. The loop they close: HARNESS produces evidence,
the user locks a static config, SIDECAR applies and meters it, drift triggers
the next calibrate.

![Interaction flows diagram](interaction-flows-v0.3.svg)

*v0.1 implements the SIDECAR half; HARNESS mode is the v0.2 headline. These
diagrams predate the product rename (labels read "arcp" — the working name of
the control-plane research line this design was distilled from).*
