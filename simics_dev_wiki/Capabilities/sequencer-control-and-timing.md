[← Device Overview](overview.md)

---

# sequencer-control-and-timing

This page documents the Simics DML capability "sequencer-control-and-timing" implemented by the Simics DML device dmr_imh_hwrs_fv (reset sequencer / HWRS behavior). It is organized for three target audiences: Simics Device Model Developers, Software Feature Validators, and Platform Architects.

Source files:
- srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml — sequencer FSM, port drivers, events, helpers. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*
- srv-pm/code/hwrs-gen2/attributes.dml — configuration and saved attributes (timeouts, fuses, flags). *Source: srv-pm/code/hwrs-gen2/attributes.dml*

---

## Overview

What this models
- Models the DMR/IMH hardware reset sequencer (HWRS) that is driven by a software-visible step counter (reset_seq_fsm.reset_seq_step). The sequencer executes an internal command table of reset phases, paced by programmed delays, posts sequencer events, and updates completion counters when reset flows finish.
- Software-visible artifacts include:
  - reset_seq_fsm.reset_seq_step — the program counter / current sequencer table index.
  - reset_seq_fsm.reset_seq_wr_seq_done — monotonic counter of warm-reset completions.
  - Various saved attributes (booleans and numeric timeouts) visible to SW and preserved across Simics checkpoints.

Scope — simulated vs stubbed
- Simulated:
  - Table-driven sequencer index and advancement via auto_increase template methods.
  - Input signal handling via pin_state_notifier / reset_seq_fsm_driver which invoke sequencer helpers.
  - Timed pacing via infra_timer after-handlers and one-shot sequencer events (reset_sequencer_event) with delays computed from per-step parameters and configurable attributes (preamble_timeout_us, didt_timeout_us, pltrst_effect_delay_multiple, etc.).
  - Saved attributes and configuration templates (bool_attr, uint64_attr) that persist across checkpoint/restore.
- Stubbed / simplified:
  - The sequencer stores and advances a numeric index rather than modeling a full microcoded internal state machine with named states — phases are implicit in table entries.
  - MMIO writes to reset_seq_fsm.reset_seq_step do not trigger FSM transitions (writes only store the value); only the auto_increase-driven increase_one() is used to advance atomically.
  - Any hardware-side signal drivers external to the device (other board-level devices) are represented as input ports; the external devices themselves are not modelled here.

*Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*

---

## How It's Simulated

DML constructs used
- Registers / saved state:
  - reset_seq_fsm.reset_seq_step — implemented using the auto_increase typed template (exposes increase_one()) and stored as DML field. Reads return live step index used by get_seq_params() and sequencer helpers.
  - reset_seq_fsm.reset_seq_wr_seq_done — implemented using auto_increase; incremented by reset_sequencer_done() to record warm-reset completions.
  - Other status and control values are implemented as bool_attr / uint64_attr saved attributes (e.g., is_primary_imh, aux_pwr_retained_register, trigger_cold_rst_exit_done).
  *Source: srv-pm/code/hwrs-gen2/attributes.dml*
- Ports / signal interfaces:
  - Input ports are implemented via pin_state_notifier and reset_seq_fsm_driver objects. Handlers implement on_change()/signal_raise() and call sequencer helpers or post events.
  - Examples: s3m_rclk_programming_done, fdfx_powergood_rst_b, imh2cbb_hwsync_ack_in, cro_clk_valid.
  *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*
- Timers and events:
  - infra_timer after-handlers are used to pace microsecond-level delays between sequencer phases.
  - reset_sequencer_event is a one-shot event that, on expiry, advances the sequencer and may invoke completion logic.
  *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*
- Helpers / FSM operations:
  - reset_sequencer_next() — computes per-step delay via get_seq_params(seq_step) and posts reset_sequencer_event.
  - reset_sequencer_done() — called when final step reached for warm-reset flows; increments reset_seq_wr_seq_done via auto_increase.increase_one().
  *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*

Checkpoint behaviour
- All saved attributes and auto_increase-backed counters are preserved across Simics checkpoint/restore cycles via standard DML saved attributes. Timers and pending events follow Simics event checkpoint semantics.

---

## Working Flow

Detailed step-by-step behaviour, registers, signals, and event scheduling.

Primary model of operation
- The sequencer is driven by a numeric program counter (reset_seq_fsm.reset_seq_step). The device advances the counter using the auto_increase template's increase_one() method when a sequencer step completes. The behaviour is table-driven: get_seq_params(seq_step) returns the timing parameters and command index for the given step.

Key flows

1) FLOW: reset-sequencer-step-advance
- Trigger: SW action or an input port edge that calls reset_sequencer_next() (for example, s3m_rclk_programming_done.signal_raise()).
- Sequence:
  1. Port handler on_change(true) (registered via reset_seq_fsm_driver / pin_state_notifier) receives the input edge for s3m_rclk_programming_done.
  2. The handler calls reset_sequencer_next().
  3. reset_sequencer_next() reads reset_seq_fsm.reset_seq_step.get() and computes per-step parameters via get_seq_params(seq_step).
  4. It posts reset_sequencer_event (a one-shot) with a delay computed using values returned by get_seq_params and configuration attributes such as preamble_timeout_us, didt_timeout_us and pltrst_effect_delay_multiple.
  5. When reset_sequencer_event expires its callback advances the sequencer via reset_seq_fsm.reset_seq_step.increase_one().
- Result: software-visible reset_seq_fsm.reset_seq_step reflects the new index.

2) FLOW: warm-reset-completion-increment
- Trigger: sequencer reaches final warm-reset step and confirms exit condition.
- Sequence:
  1. FSM calls reset_sequencer_done().
  2. reset_sequencer_done() calls reset_seq_fsm.reset_seq_wr_seq_done.increase_one() — atomic increment.
  3. The incremented counter is preserved across checkpoints.
- Result: reset_seq_fsm.reset_seq_wr_seq_done is a monotonically increasing count readable by software.

3) FLOW: secondary-imh-hwsync-ack-handling
- Trigger: imh2cbb_hwsync_ack_in.signal_raise() when is_primary_imh == false.
- Sequence:
  1. on_change(true) handler checks is_primary_imh attribute.
  2. If configured as secondary, the handler posts or advances sequencer state (calls reset_sequencer_next() or other ack-related logic).
  3. infra_timer callbacks (if any) run to pace subsequent steps.
- Result: sequencer advances or synchronisation proceeds; reset_seq_fsm.reset_seq_step updated and follow-up outputs driven as per later table entries.

Registers involved and semantics
- reset_seq_fsm.reset_seq_step
  - Read: returns live step index used by sequencer logic.
  - Write: raw MMIO write stores value but does not trigger FSM transitions; only increase_one() is used for atomic advancement.
  *Behavior note: software must not expect MMIO write to step the sequencer.* *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*
- reset_seq_fsm.reset_seq_wr_seq_done
  - Read: returns the stored warm-reset completion count.
  - Write: external writes store a value via DML default behavior; functional increments are done via auto_increase.increase_one() called by sequencer code.
  *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*

Interface signals (ports) and conditions
- s3m_rclk_programming_done (PORT, input): asserted when S3M RCLK programming completes. on_change(true) triggers reset_sequencer_next().
- fdfx_powergood_rst_b (PORT, input): power-good / reset line (active low). on_change() may be used as a trigger in some phases.
- imh2cbb_hwsync_ack_in (PORT, input): hardware sync ack from CBB; when device is secondary (is_primary_imh == false), assertion advances sequencer or participates in sync flow.
- cro_clk_valid (PORT, input): clock-valid signal; used by FSM guards to enable sequencer phases.
*All port handlers are implemented via pin_state_notifier / reset_seq_fsm_driver and call sequencer helpers. Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*

Event scheduling
- reset_sequencer_event: posted by reset_sequencer_next() (one-shot). Delay is computed from get_seq_params(seq_step) and device attributes (preamble_timeout_us, didt_timeout_us, unwind_timeout_us, scaled by pltrst_effect_delay_multiple). Expiry calls increase_one() and may call reset_sequencer_done() if final.
- infra_timer after-handlers: used where precise microsecond pacing is required. They may post reset_sequencer_event, perform checks, or schedule follow-up timers. Timers can be cancelled on sequencer exit or device reset.

---

## Register Map

| Register                                | Bank | Access Type | Reset Value | Write Side-Effect                                                                                         | Read Side-Effect                                                                   |
|-----------------------------------------|------|-------------|-------------|-----------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|
| reset_seq_fsm.reset_seq_step            | N/A  | RW          | implementation-defined | MMIO write stores value but does NOT trigger FSM transitions. Atomic advancement is performed by increase_one(). | Read returns the live sequencer index used by get_seq_params() (no side-effect).  |
| reset_seq_fsm.reset_seq_cr_seq_done     | N/A  | RO?*        | implementation-defined | N/A                                                                                                       | N/A                                                                                |
| reset_seq_fsm.reset_seq_wr_seq_done     | N/A  | RW          | implementation-defined | MMIO write updates stored counter per DML default. Functional increments are performed only via auto_increase.increase_one() called by reset_sequencer_done(). | Read returns a monotonic completion count (no side-effect).                      |

Notes:
- Bank and precise reset values are defined in DML and are device-specific; consult the DML files for exact initial values. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml, srv-pm/code/hwrs-gen2/attributes.dml*
- reset_seq_cr_seq_done appears in code map with no explicit behavior defined in the analysis; treat as device-reserved or read-only status unless DML indicates otherwise.

---

## Interface Signals

All signals below are input PORTs to this device (device receives these signals). Each is implemented with a notifier/driver that invokes on_change()/signal_raise().

| Signal                        | Direction | Interface Type | Trigger Condition                              | Action (on trigger)                                                                 |
|-------------------------------|-----------|----------------|------------------------------------------------|-------------------------------------------------------------------------------------|
| s3m_rclk_programming_done     | IN        | PORT (pin)     | asserted (true) when S3M RCLK programming done | on_change(true) → reset_sequencer_next() → posts reset_sequencer_event with delay  |
| fdfx_powergood_rst_b          | IN        | PORT (pin)     | edge on active-low power-good/reset             | on_change() → sequencer guards check state; may post events or cancel timers       |
| imh2cbb_hwsync_ack_in         | IN        | PORT (pin)     | asserted when CBB hardware sync ack arrives     | on_change(true) → if is_primary_imh == false then advance sequencer / post event   |
| cro_clk_valid                 | IN        | PORT (pin)     | asserted when clock domain is valid             | on_change() → used by sequencer guards to allow phases requiring clock validity    |

*Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*

---

## Behavioral Specification (for Software Feature Validators)

Each entry is a precise WHEN → THEN statement suitable for writing assertions or test steps.

1. WHEN s3m_rclk_programming_done is asserted → THEN reset_sequencer_event is posted with a delay computed from get_seq_params(current_step) and configured timeout attributes (preamble_timeout_us / didt_timeout_us / pltrst_effect_delay_multiple). After the event expires, reset_seq_fsm.reset_seq_step increments by one (atomic increase_one()) and reads reflect the new step index. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*

2. WHEN the sequencer reaches its final warm-reset step and the final-step exit condition is confirmed → THEN reset_sequencer_done() increments reset_seq_fsm.reset_seq_wr_seq_done by one (atomic monotonic increment) and that increment is readable by software. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*

3. WHEN imh2cbb_hwsync_ack_in is asserted and is_primary_imh == false → THEN the handler calls reset_sequencer_next() (or equivalent ack-handling logic) resulting in scheduled sequencer advancement; subsequent infra_timer callbacks are used to pace follow-up steps. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*

4. WHEN software writes a value to reset_seq_fsm.reset_seq_step via MMIO → THEN the written value is stored but the sequencer does not advance or execute side-effect actions; only increase_one() invoked internally causes a functional step advance. (Write has no FSM transition side-effect.) *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*

5. WHEN an infra_timer after-handler posts reset_sequencer_event and the device is reset/cancel path executed before event expiry → THEN the pending reset_sequencer_event is cancelled (or ignored) and the sequencer does not advance for that scheduled expiry. (Timer cancellation occurs on explicit sequencer cancel or device reset.) *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*

6. WHEN pltrst_effect_delay_multiple or preamble_timeout_us attributes are modified → THEN subsequent reset_sequencer_event delays computed by get_seq_params() are affected (e.g., pltrst scaling factors modify effective delays) and observable sequencer pacing changes on the next scheduled steps. *Source: srv-pm/code/hwrs-gen2/attributes.dml*

---

## Test Case Scenarios (for Software Feature Validators)

Provide concrete scenarios suitable for automated Simics test scripts.

Scenario 1
- Setup: Device in initial state; reset_seq_fsm.reset_seq_step = N (known). Ensure s3m_rclk_programming_done is de-asserted.
- Action: Assert s3m_rclk_programming_done (raise signal).
- Expected Result: reset_sequencer_event is posted; after computed delay, reset_seq_fsm.reset_seq_step == N+1.
- Verification Point: Read reset_seq_fsm.reset_seq_step before and after delay; verify a single increment.

Scenario 2
- Setup: Configure device so sequencer is one step away from final warm-reset exit. Record reset_seq_fsm.reset_seq_wr_seq_done = K.
- Action: Trigger the final step (e.g., raise the appropriate input signal or call the code path emulating final step).
- Expected Result: reset_seq_fsm.reset_seq_wr_seq_done == K+1 after completion.
- Verification Point: Read reset_seq_fsm.reset_seq_wr_seq_done and assert monotonic increment.

Scenario 3
- Setup: Set is_primary_imh = false and reset_seq_fsm.reset_seq_step = M.
- Action: Assert imh2cbb_hwsync_ack_in.
- Expected Result: sequencer advances (reset_seq_fsm.reset_seq_step == M+1 after scheduled delay) and infra_timer callbacks run as needed.
- Verification Point: Confirm reset_seq_fsm.reset_seq_step changed; optionally validate that subsequent outputs or flags set by the next table entry take expected values.

Scenario 4
- Setup: reset_seq_fsm.reset_seq_step = P.
- Action: Write value Q to reset_seq_fsm.reset_seq_step via MMIO where Q != P.
- Expected Result: Register read returns Q, but no event or FSM transition occurs (no side-effect).
- Verification Point: Read register; confirm no timers posted and no subsequent increase_one() occurred as measured by no change in reset_seq_wr_seq_done or no external outputs.

Scenario 5 (timing/config attribute effect)
- Setup: Set preamble_timeout_us = X and pltrst_effect_delay_multiple = Y. Record current step S.
- Action: Trigger reset_sequencer_next() (via port assert).
- Expected Result: The scheduled delay until the next step equals computed_delay = base_delay_from_table(S) adjusted by X and scaled by Y. After expiry, step increments.
- Verification Point: Measure time between trigger and step increment in simulation; assert it matches expected computed_delay within simulator timing resolution.

---

## Implementation Notes (for Simics Device Model Developers)

Key source files
- srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml — primary FSM code, port drivers, event definitions, sequencer helpers (reset_sequencer_next, reset_sequencer_done), infra_timer interactions. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*
- srv-pm/code/hwrs-gen2/attributes.dml — timeout and feature attributes (preamble_timeout_us, didt_timeout_us, unwind_timeout_us, pltrst_effect_delay_multiple, sku_feature_dword8/9, is_primary_imh, trigger_cold_rst_exit_done, aux_pwr_retained_register). *Source: srv-pm/code/hwrs-gen2/attributes.dml*

Template dependencies and implementations
- auto_increase template — used for reset_seq_fsm.reset_seq_step and reset_seq_wr_seq_done; provides increase_one() semantics for atomic increments. The implementation expects device code to call increase_one() for functional advancement rather than relying on MMIO writes.
- bool_attr / uint64_attr templates — used for persistent saved flags and numeric timeouts.
- pin_state_notifier / reset_seq_fsm_driver — used for implementing port handlers and on_change callbacks wired to external signals.
- infra_timer — used to realize microsecond-scale delays and to post reset_sequencer_event.

Extension / override points
- get_seq_params(seq_step) — central place to map a step index to timing and command parameters; override or extend to change the command table or timing profiles.
- port driver on_change handlers — can be extended to add additional guard logic or to implement alternative triggers.
- reset_sequencer_next() and reset_sequencer_done() — primary helpers; override to add custom side-effects (e.g., driving outputs) or to change when counters are incremented.
- Event and timer handling — change scheduling logic (for example, to convert delays to different timebase units) by modifying infra_timer usage or reset_sequencer_event posting.

Simulation fidelity and known differences from silicon
- Sequencer uses a numeric table index rather than a full named-state machine; this simplifies the model but maps phasing implicitly to table entries.
- MMIO writes to step register do not cause functional advancement — on real hardware writes may have different semantics (verify HW spec). The Simics model intentionally requires increase_one() for functional advancement to avoid races in the simulated environment.
- Timer granularity is Simics-internal; microsecond timing is simulated but may not match real hardware jitter or micro-architectural effects.
- Some outputs and board-level interactions are modelled only as input ports or no-op placeholders; full board-level co-simulation is required to validate end-to-end physical signal flows.

Debugging and tracing tips
- Trace infra_timer postings and reset_sequencer_event postings to confirm computed delays.
- Log calls to increase_one() to confirm atomic advancement semantics.
- Watch saved attributes to ensure checkpoint/restore preserves intended state (saved attributes are standard DML saved types).

---

## Platform Integration Notes (for Platform Architects)

Role in system/platform
- The HWRS/sequencer models the reset sequencing and handshake required between IMH, platform controllers (CBB), power-management logic, and clock domains. It is central to implementing correct reset ordering and detection of reset flow completion (particularly warm resets).

Required signal connections (counterparts)
- s3m_rclk_programming_done — source: S3M / RCLK programming block. Must be connected to indicate completion of RCLK programming before certain sequencer steps.
- imh2cbb_hwsync_ack_in — source: CBB / platform fabric hardware sync agent (HW sync ack). Required when device acts as secondary IMH to follow primary-driven synchronization flows.
- fdfx_powergood_rst_b — source: power-good monitor or platform power-management logic. Used to gate reset phases that depend on power-good conditions.
- cro_clk_valid — source: clock management / CRO that indicates that required clocks are stable and valid prior to clock-dependent phases.

Dependencies on other device capabilities or services
- Power-management device(s) (providing fdfx_powergood_rst_b, aux power retention signals).
- Clock management device(s) (providing cro_clk_valid).
- Board-level sync controllers (providing imh2cbb_hwsync_ack_in).
- Software or platform firmware is expected to read sequencer registers and react to completion counters.

Configuration parameters that affect behaviour
- preamble_timeout_us, didt_timeout_us, unwind_timeout_us — microsecond timeout parameters used to compute per-step delays. *Source: srv-pm/code/hwrs-gen2/attributes.dml*
- pltrst_effect_delay_multiple — scaling factor applied to certain delays (affects how PLTRST changes impact phase timing). *Source: srv-pm/code/hwrs-gen2/attributes.dml*
- is_primary_imh — boolean determining primary vs secondary IMH behaviour and how hardware sync acknowledgements are handled. *Source: srv-pm/code/hwrs-gen2/attributes.dml*
- sku_feature_dword8/9 and related fuse attributes — may gate specific sequence entries or timing variations per platform SKU. *Source: srv-pm/code/hwrs-gen2/attributes.dml*
- trigger_cold_rst_exit_done, aux_pwr_retained_register — saved flags that change how exit conditions are evaluated and retained across power transitions.

Integration checklist
- Connect the expected input PORTs to the platform model’s corresponding signals.
- Ensure platform firmware or test harness knows that sequencer advancement occurs via event/timer callbacks and that MMIO writes to step register do not advance the sequencer.
- Ensure timing attributes are set according to platform timing budgets to obtain realistic pacing in simulation.

---

If you need, I can:
- produce concrete Simics Python test scripts that assert the WHEN→THEN behaviors above;
- extract the exact DML lines for each attribute/register for direct citation and quick code navigation.