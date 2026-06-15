[← Device Overview](overview.md)

---

# Capability: pin-and-signal-drive (dmr_imh_hwrs_fv)

This page documents the Simics DML capability "pin-and-signal-drive" implemented by the dmr_imh_hwrs_fv device. It covers: what is modelled, how it is implemented, precise observable behavior for validation, test scenarios, developer implementation notes and platform integration guidance.

Source pointers are included inline. *Source: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml; srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml; srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml; common/code/platform-common/unified-common-code/signals/signal-templates.dml.*

---

## Overview

- What is modelled
  - Read-only resolved IP-disable registers: sb_cr.IP_DISABLE_RESOLVED_CR_DWORD0 and sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3. Each read returns the bitwise OR of software-controlled disable bits and fuse bits (a resolved snapshot).
  - Output sideband/power-management signals driven by the device (CONNECT outputs) such as vinf_iso_b, vinf_pwrgood_rst_b, vref_iso_b, s3m_early_comm_open, sblink_bringup, imh2cbb_hwsync_req_out, etc. These are modelled as digital level-held outputs driven through pin templates and logged under the pwrgd_reset log group.

- Role in device
  - Provides resolved disable state to software via the resolved IP-disable registers.
  - Drives HW reset / power-management / sideband signals to downstream devices during reset/power sequencing flows.

- Scope: simulated vs stubbed
  - Simulated: logical resolution of disable bits (cr_reg.val | fuses_reg.val) on register read; explicit CONNECT-level pin signal assertions/deassertions (signal_raise/signal_lower) with log messages; read-only semantics for resolved registers.
  - Stubbed / not modelled: analog/electrical behavior, precise timing models for signal edges beyond immediate level changes, internal FSM state machine for sequence timing (no FSM provided in this capability description), and any hardware side-effects beyond the remote CONNECT signal level.

*Source: capability analysis data; template and register file list above.*

---

## How It's Simulated

- Register implementation
  - The two resolved registers use the ip_disable_resolved_cr_reg template. The template supplies a read_register callback that delegates to a get() helper. get() returns the resolved snapshot: cr_reg.val | fuses_reg.val. Reads present this 64-bit resolved value to the reader. The resolved registers are modelled as read-only; no write handlers are defined and writes are ignored/silently discarded. *Source: srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml; srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml.*

- Pin / signal outputs
  - Output signals are implemented with the c_pin_out template. c_pin_out delegates to a helper template c_pin_out_hap to perform the CONNECT-level action (signal_raise / signal_lower). When the model drives a pin, the c_pin_out/c_pin_out_hap sequence makes the CONNECT call to the remote device and emits log messages under the pwrgd_reset log group. Signals are level-held outputs; no timing delays or drive-strength modelling is present. *Source: srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml; common/code/platform-common/unified-common-code/signals/signal-templates.dml.*

- Other DML constructs
  - No explicit FSM or timed event scheduling is described in this capability (state & event scheduling sections not available). All pin changes are synchronous immediate model actions (initiated by internal model code or handlers elsewhere in the device).

---

## Working Flow

Two principal flows are modelled:

1) read-resolved-ip-disable
- Trigger: external agent performs a register read of sb_cr.IP_DISABLE_RESOLVED_CR_DWORD0 or sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3.
- Steps:
  1. Simics invokes sb_cr.IP_DISABLE_RESOLVED_CR_DWORDx.read_register (provided by ip_disable_resolved_cr_reg).
  2. read_register calls get().
  3. get() computes and returns cr_reg.val | fuses_reg.val (64-bit).
- Result: the reader receives the resolved IP-disable snapshot (software OR fuse bits).

2) drive-output-pin
- Trigger: device model code requests a change to an output pin (internal handler or sequence).
- Steps:
  1. Code sets the c_pin_out value (to assert or deassert).
  2. c_pin_out delegates to c_pin_out_hap.
  3. c_pin_out_hap issues the CONNECT-level call to the remote device (signal_raise/signal_lower) and emits a log entry under the pwrgd_reset log group.
  4. The remote device observes the driven level on the connected signal.
- Result: the CONNECT output is asserted or deasserted. The action is immediate (no modeled delay).

Note: There are no described internal timers or scheduled deferred actions for this capability. All behavior is synchronous with the caller's action. *Source: capability analysis and code map.*

---

## Register Map

| Register                                         | Bank   | Access Type | Reset Value | Write Side-Effect           | Read Side-Effect                                         |
|--------------------------------------------------|--------|-------------|-------------|-----------------------------|----------------------------------------------------------|
| sb_cr.IP_DISABLE_RESOLVED_CR_DWORD0              | sb_cr  | RO          | 0x0         | Writes ignored / discarded  | Returns cr_reg.val | fuses_reg.val (resolved snapshot)                       |
| sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3              | sb_cr  | RO          | 0x0         | Writes ignored / discarded  | Returns cr_reg.val | fuses_reg.val (resolved snapshot)                       |

(Access types and effects derived from register side-effect description; both registers modelled read-only with init_val=0x0.) *Source: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml; srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml.*

---

## Interface Signals

All signals listed below are CONNECT outputs (device drives them). Trigger and action describe the model conditions and actions.

| Signal                     | Direction | Interface Type | Trigger Condition                              | Action / Effect on CONNECT |
|----------------------------|-----------|----------------|------------------------------------------------|-----------------------------|
| vref_iso_b                 | OUT       | signal (CONNECT) | Model requests isolation assert/deassert       | signal_raise/signal_lower on CONNECT; logged pwrgd_reset |
| vinf_iso_b                 | OUT       | signal (CONNECT) | Model requests vinf isolation assert/deassert  | signal_raise/signal_lower; logged pwrgd_reset |
| vinf_pwrgood_rst_b         | OUT       | signal (CONNECT) | Model asserts reset during power sequencing    | driven low/high on CONNECT; logged pwrgd_reset |
| vref_iso_b                 | OUT       | signal (CONNECT) | Active-low voltage-reference-isolation output  | level-held; logged pwrgd_reset |
| s3m_early_comm_open        | OUT       | signal (CONNECT) | Early comm channel open/close                  | driven true/false; logged pwrgd_reset |
| sblink_bringup             | OUT       | signal (CONNECT) | B-ringup phase requested                       | driven asserted/deasserted; logged pwrgd_reset |
| imh2cbb_hwsync_req_out     | OUT       | signal (CONNECT) | HW sync request from IMH to CBB                | driven asserted/deasserted; logged pwrgd_reset |

Notes:
- All outputs are level-held and use the c_pin_out -> c_pin_out_hap sequence to enact the CONNECT call. The log group used is pwrgd_reset. *Source: capability analysis and pwrgd-reset template files.*

---

## Behavioral Specification (for Software Feature Validators)

Each item is a precise WHEN -> THEN statement suitable for automated tests.

1. WHEN a software or external agent reads sb_cr.IP_DISABLE_RESOLVED_CR_DWORD0 -> THEN the returned 64-bit value equals (cr_reg.val | fuses_reg.val) as seen at the time of the read.
   - Verification: compare register read against independently set cr_reg and fuses_reg snapshots.

2. WHEN a software or external agent reads sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 -> THEN the returned 64-bit value equals (cr_reg.val | fuses_reg.val) for DWORD3 fields.
   - Verification: same as above for DWORD3 fields.

3. WHEN software writes any value to sb_cr.IP_DISABLE_RESOLVED_CR_DWORD0 or _DWORD3 -> THEN the write has no effect on the resolved register (reads continue to return cr_reg.val | fuses_reg.val) and no write-side callbacks are invoked.
   - Verification: write register; immediately read it and verify value unchanged except as reflected by cr_reg/fuses_reg; check logs for absence of write handlers.

4. WHEN the model executes a c_pin_out for an output (for example asserting vinf_iso_b) -> THEN the CONNECT to the remote device receives a signal_raise (active level) and a log entry in log group pwrgd_reset is emitted indicating the driven state change.
   - Verification: inspect the remote CONNECT signal state in Simics, and check pwrgd_reset log entries for the expected message.

5. WHEN the model deasserts a previously asserted pin (for example deassert vinf_pwrgood_rst_b) -> THEN the CONNECT receives signal_lower (inactive level) and a matching pwrgd_reset log entry is emitted.
   - Verification: remote CONNECT shows level change; log contains deassert message.

6. WHEN only the fuse bit for a resolved-disable field is set and the software control bit is clear -> THEN reads of the corresponding resolved register bit are reported as set (1) because fuse OR software => 1.
   - Verification: set fuses_reg bit, clear cr_reg bit, read resolved register and confirm bit set.

7. WHEN only the software control bit is set and fuse bit is clear -> THEN reads of the resolved register bit are reported as set (1).
   - Verification: set cr_reg bit, clear fuses_reg bit, read resolved register and confirm bit set.

(These behaviors are deterministic and synchronous in the model — no deferred timing.)

*Source: ip_disable_resolved_cr_reg behavior and c_pin_out/c_pin_out_hap descriptions.*

---

## Test Case Scenarios (for Software Feature Validators)

1) Resolved register: software-only bit set
- Setup: Ensure fuses_reg bit X = 0; set cr_reg bit X = 1 (via the underlying software-control register that feeds cr_reg).
- Action: Read sb_cr.IP_DISABLE_RESOLVED_CR_DWORD0.
- Expected Result: Returned register's bit X == 1.
- Verification Point: Register read equals cr_reg.val | fuses_reg.val; log no write activity on resolved register.

2) Resolved register: fuse-only bit set
- Setup: Set fuses_reg bit Y = 1 (through fuse model), set cr_reg bit Y = 0.
- Action: Read sb_cr.IP_DISABLE_RESOLVED_CR_DWORD0.
- Expected Result: Returned register's bit Y == 1.
- Verification Point: Read value matches OR result; confirm write attempts to resolved register are ignored.

3) Resolved register: write ignored
- Setup: Read initial value V0 of sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3.
- Action: Attempt a write to sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 with a different value V1.
- Expected Result: Read still returns V0 (unless underlying cr_reg/fuses_reg changed by other actions).
- Verification Point: No change in readback; absence of write-side logs/handlers.

4) Pin drive assert: vinf_iso_b
- Setup: Connect the device's vinf_iso_b CONNECT to a simple stub remote device or probe.
- Action: Cause model handler to assert vinf_iso_b (simulate the model action that sets the c_pin_out).
- Expected Result: Remote signal level reads as asserted (active-low: driven low); pwrgd_reset log contains an entry stating the pin was driven.
- Verification Point: Inspect remote CONNECT state and simulation log.

5) Pin deassert and log verification: vinf_pwrgood_rst_b
- Setup: Initially assert vinf_pwrgood_rst_b.
- Action: Cause model to deassert vinf_pwrgood_rst_b.
- Expected Result: Remote signal goes inactive (high); pwrgd_reset log contains deassert message.
- Verification Point: CONNECT state and pwrgd_reset log entries.

6) Combined resolved behavior (both fuse and software set)
- Setup: Set both fuses_reg bit Z = 1 and cr_reg bit Z = 1.
- Action: Read sb_cr.IP_DISABLE_RESOLVED_CR_DWORD0.
- Expected Result: bit Z == 1 (remains 1).
- Verification Point: consistency of resolved read irrespective of which source set the bit.

Notes for testers:
- Access to underlying cr_reg and fuses_reg may require interacting with other model registers or configuration; tests should set those via the correct model interfaces (the model places software-control and fuse bits into those backing registers).
- Logs are emitted under pwrgd_reset. Use Simics logging facilities to capture and assert on these messages. *Source: pwrgd-reset-templates.dml and capability analysis.*

---

## Implementation Notes (for Simics Device Model Developers)

- Key DML source files implementing this capability
  - sb_cr register declarations and resolved registers: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml
  - ip-disable templates / resolved register template: srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml
  - pwrgd/pin drive templates and pin declarations: srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml; srv-pm/code/hwrs-gen2/pwrgd-reset-pins.dml; srv-pm/code/hwrs-gen2/hwrs-nac-pins.dml
  - signal templates: common/code/platform-common/unified-common-code/signals/signal-templates.dml
  - Supporting attribute & register bank code: srv-pm/code/hwrs-gen2/attributes.dml; srv-pm/code/hwrs-gen2/reg-banks-impl.dml
  - Reset / sequencer context referenced by pins: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml; srv-pm/code/hwrs-gen2/resetbus.dml
  *Source: Code Map list in capability analysis.*

- Template dependencies and call graph
  - ip_disable_resolved_cr_reg: provides read_register -> get() which computes cr_reg.val | fuses_reg.val.
  - c_pin_out template: used to expose output pin properties and public API to model code; delegates to c_pin_out_hap.
  - c_pin_out_hap: helper that executes the CONNECT signal call (signal_raise/signal_lower) and issues log entries (group pwrgd_reset).
  - The resolved register templates reference backing registers cr_reg and fuses_reg; ensure backing register names and bank placements are consistent with the device's register bank definitions.
  *Source: capability analysis snippets and template file listings.*

- Extension / override points
  - To change resolution logic: extend/override ip_disable_resolved_cr_reg.get() to incorporate additional sources or different merge rules (e.g., masking, prioritization).
  - To attach write-side behavior: add write_register or after_write handlers in the resolved register declaration to trap writes (currently ignored).
  - To alter logging or signal behavior: override c_pin_out_hap or wrap its invocation to add timing, additional validation, or alternate log groups.
  - To add new pins: declare additional c_pin_out entries in device DML and wire them to CONNECTs; reuse c_pin_out_hap for consistent behavior.
  *Source: typical DML extension patterns and templates referenced.*

- Simulation fidelity / known differences from hardware
  - The model provides logical, functional fidelity for resolved disable reads (accurate OR of software and fuse bits).
  - Pin outputs are driven at the CONNECT/signal level immediately; no electrical behavior (rise/fall times, drive strength, bus contention) or analog effects are modelled.
  - No timing/FSM for sequence delays is included in this capability (level-held outputs only). Where hardware sequencing with precise delays or arbitration matters, additional sequencer/FSM templates must be integrated.
  - Writes to the resolved registers are ignored in the model; on real silicon the resolved view may be read-only but the underlying software register may be writable — ensure tests target the appropriate underlying registers for writes. *Source: capability analysis registers & templates.*

---

## Platform Integration Notes (for Platform Architects)

- Role in the overall Simics platform
  - This capability supplies two functions: (1) readable resolved IP-disable state for firmware/software and (2) driven sideband/power-management pins used by downstream devices and power/reset sequencing. It participates in platform bring-up and reset sequencing flows. *Source: capability overview and pwrgd-reset templates.*

- Required CONNECT/PORT connections and counterparts
  - Each output signal (e.g., vinf_iso_b, vinf_pwrgood_rst_b, vref_iso_b, s3m_early_comm_open, sblink_bringup, imh2cbb_hwsync_req_out) must be CONNECTed to a remote device that expects that sideband signal (downstream power-management or companion IP blocks). The remote endpoints should implement the corresponding signal/PORT and respond to signal_raise/signal_lower semantics.
  - There are no input PORTs identified for this capability. If the platform requires feedback (e.g., sensing remote rail state), those ports must be added and connected externally. *Source: Interface Output list and capability analysis.*

- Dependencies on other device capabilities or platform services
  - Fuse model: resolved reads depend on a fuses_reg backing store; platform must provide fuse values through the fuse model or configuration that binds to the fuses_reg referenced by ip_disable_resolved_cr_reg.
  - Software-control register owners: the cr_reg values (software control) are supplied by other device register implementations or by firmware accesses; these must be present and wired so that ip_disable_resolved_cr_reg.get() sees their current values.
  - Reset sequencer and power-management flows: while this capability drives pins, higher-level sequencing (reset-sequencer-fsm) may orchestrate when those pins are toggled. Integration with reset-sequencer-fsm is expected for full platform sequencing. *Source: code map references to fuses and reset sequencer files.*

- Configuration parameters
  - There are no explicit per-device configuration parameters documented for this capability; pin names and resolved register mappings are declared in the device DML. Platform maintainers can configure initial fuse values via the fuse model or initial register/init_val fields. *Source: register init_val and fuse references.*

- Integration guidance
  - Ensure all outputs are CONNECTed in the platform model to appropriate consumers before executing power/reset sequences.
  - Provide the fuse values and ensure software-control registers are accessible so resolved reads reflect realistic behavior.
  - If required, extend the model to include timing/sequence FSMs to emulate platform-specific reset timing; the current implementation performs immediate level changes only.

---

If you need, I can:
- produce concrete Simics Python test scripts that implement the test scenarios above,
- produce a concise checklist for integrating these CONNECTs into a platform DML, or
- show the minimal DML snippets to override get() or wire a new c_pin_out.