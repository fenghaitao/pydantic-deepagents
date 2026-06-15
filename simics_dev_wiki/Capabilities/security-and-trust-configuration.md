[← Device Overview](overview.md)

---

# Capability: security-and-trust-configuration (dmr_imh_hwrs_fv)

This page documents the Simics DML device capability implemented by the dmr_imh_hwrs_fv model that provides a limited set of security-and-trust configuration behaviors: resolved IP-disable register reads, PUF readiness input handling, HWRS-driven output CONNECTs, and strap configuration attributes.

Source: *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*

---

## Overview
This capability models a subset of the hardware security-and-trust configuration behaviors required by platform bring-up and validation:

- Exposes a resolved IP-disable register value (sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3) that returns the logical OR of a software-writable register and a hardware fuses register.
- Models a PUF-ready input line (puf_ip_ready) as a port. Incoming transitions update an internal level and invoke configured change handlers.
- Exports several HWRS-driven outputs (examples: puf_rst_b, hwrs_mc_pstate, scu_start_pmsync_handshake) as CONNECTs driven by c_pin_out templates.
- Exposes configuration straps as model attributes (strap_txt_plten, strap_txt_agent) implemented with uint64_attr.

Scope:
- Simulated: read semantics for the resolved IP-disable register (read callback), PUF-ready input handling and notifications, output pin drive through c_pin_out templates, strap attributes saved and returned by getters.
- Stubbed / not modeled: detailed hardware FSMs for HWRS sequencing, register side-effects other than the resolved OR behavior, event scheduling/timers, and complex fuse-programming flows. There is no modeled multi-step hardware handshake or internal state machine beyond the internal level and attribute storage mentioned above.

Relevant DML templates used: ip_disable_resolved_cr_reg, pin_state_notifier, c_pin_out / c_pin_out_hap, uint64_attr.
Source: *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*

---

## How It's Simulated
Key simulation constructs and their roles:

- ip_disable_resolved_cr_reg (register with read_register callback)
  - Implements reads of sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3. The read_register callback computes the resolved value by ORing the software register state (cr_reg.val) and the hardware fuse state (fuses_reg.val) and returns the DWORD result.
  - Behavior realized via a get() call inside the callback and returning cr_reg.val | fuses_reg.val.
  - Source: *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*

- pin_state_notifier (port / pin-state implementation)
  - Implements the PUF readiness input port (puf_ip_ready). A signal_raise on this port invokes the configured on-change handlers. The handler updates an internal "level" register, notifies observers, and calls the device-change handler.
  - This is the mechanism by which the model detects an asserted PUF-ready and triggers downstream behavior.

- c_pin_out / c_pin_out_hap (driven output templates)
  - Used to expose HWRS-driven CONNECTs (puf_rst_b, hwrs_mc_pstate, scu_start_pmsync_handshake). Device code drives these template instances to raise/lower downstream signals. c_pin_out inherits behavior to notify HAPs and to actually change the driven wire level.

- uint64_attr (configuration straps)
  - Strap values strap_txt_plten and strap_txt_agent are exposed as uint64_attr attributes. The attribute setter updates the stored value in the model; the getter returns the saved value to callers.

What is not implemented:
- No register side-effects beyond the resolved OR behavior.
- No explicit state machine or event scheduling for HWRS sequences.
- No internal timing model for handshake delays — actions happen synchronously in callbacks/handlers.

Source: *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*

---

## Working Flow

FLOW: ip-disable-read
- Trigger: read of sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3.
- Mechanism:
  1. ip_disable_resolved_cr_reg.read_register callback executes.
  2. Callback invokes model get() to read software register (cr_reg.val) and hardware fuses (fuses_reg.val).
  3. Callback returns cr_reg.val | fuses_reg.val as the DWORD value.
- Result: Reader receives the OR of software and fuse state.

FLOW: puf-ready-assert
- Trigger: PORT signal_raise on puf_ip_ready.
- Mechanism:
  1. pin_state_notifier on-change handler runs, updates the internal level state and raises the appropriate notifications.
  2. Configured change handlers call into device-level handlers that drive c_pin_out / c_pin_out_hap instances.
  3. Driven CONNECTs (puf_rst_b, hwrs_mc_pstate, scu_start_pmsync_handshake) are toggled/asserted.
- Result: Downstream devices observing those CONNECTs see the asserted/toggled signals.

FLOW: strap-attribute-change
- Trigger: configuration write to strap_txt_plten or strap_txt_agent attribute.
- Mechanism:
  1. uint64_attr setter stores the new value in the DML attribute.
  2. Subsequent accesses (attribute getter or any callback referencing that attribute) observe the new value.
- Result: Strap attribute reflects updated configuration.

Event scheduling:
- All changes are handled synchronously via callbacks and handlers. There is no internal timer- or event-queue-driven deferred behavior modeled for this capability.

Registers involved:
- sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 (read via ip_disable_resolved_cr_reg callback).
- Software register backing the resolved value (referred to as cr_reg in the model).
- Hardware fuses register backing the resolved value (referred to as fuses_reg in the model).

Interface signals:
- Input PORT: puf_ip_ready (pin_state_notifier). Triggered by signal_raise events from the connected source.
- Output CONNECTs: puf_rst_b, hwrs_mc_pstate, scu_start_pmsync_handshake (c_pin_out instances). Driven when the device change handlers assert them.

Source: *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*

---

## Register Map

| Register                                  | Bank   | Access Type | Reset Value | Write Side-Effect | Read Side-Effect                                       |
|-------------------------------------------|--------|-------------|-------------|-------------------|--------------------------------------------------------|
| sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3       | N/A    | RO          | N/A         | none              | Returns cr_reg.val OR fuses_reg.val (resolved disable) |

Notes:
- Bank and reset value are not specified in the available model data; marked N/A.
- The resolved read behavior is implemented in the ip_disable_resolved_cr_reg read_register callback which computes the OR of software and fuses state.
Source: *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*

---

## Interface Signals

| Signal                          | Direction | Interface Type | Trigger Condition                     | Action / Effect |
|---------------------------------|-----------|----------------|---------------------------------------|-----------------|
| puf_ip_ready                    | IN        | PORT (pin_state_notifier) | signal_raise from connected PUF model | Update internal level; invoke on-change handlers that notify observers and call device change handler |
| puf_rst_b                       | OUT       | CONNECT (c_pin_out / c_pin_out_hap) | Driven by device change handler after puf_ip_ready handling | Downstream reset line driven (assert/toggle) |
| hwrs_mc_pstate                  | OUT       | CONNECT (c_pin_out / c_pin_out_hap) | Driven by device change handler | Downstream memory controller PSTATE related signal driven |
| scu_start_pmsync_handshake      | OUT       | CONNECT (c_pin_out / c_pin_out_hap) | Driven by device change handler | PM sync handshake signal driven towards SCU or equivalent |

Notes:
- The puf_ip_ready port will typically be connected to a PUF model or external test driver that performs signal_raise / signal_lower operations.
- The exact polarity and semantics of driven CONNECTs (puf_rst_b active low/high) follow naming conventions but should be validated in test harnesses; the model toggles/raises/lowers the pin per device code requests (no additional timing constraints).
Source: *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*

---

## Behavioral Specification (for Software Feature Validators)
Each statement is testable in a Simics simulation environment.

1. WHEN a guest or tester reads sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 -> THEN the returned 32-bit DWORD equals (software_register_value OR fuses_register_value).
   - Observable: read value matches bitwise OR of configured software register and fuse bits.

2. WHEN the connected PUF model performs signal_raise on puf_ip_ready -> THEN the model sets its internal PUF-ready level, invokes on-change handlers, and drives any configured outputs (for example, toggling puf_rst_b or asserting hwrs_mc_pstate).
   - Observable: c_pin_out CONNECTs change state; HAPs or signal-monitoring attached to those CONNECTs observe the change.

3. WHEN the test harness sets strap_txt_plten via the model's DML attribute setter -> THEN subsequent reads of the strap_txt_plten attribute return the written value.
   - Observable: get(attribute) returns the new uint64 value.

4. WHEN puf_ip_ready is de-asserted (signal_lower) -> THEN the internal level updates accordingly and any change handlers are invoked to reflect the de-asserted state on driven outputs.
   - Observable: driven CONNECTs reflect the de-assertion (change in driven level).

5. WHEN the software register backing the resolved IP-disable value is written to change bits -> THEN reads of sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 immediately reflect the OR of the new software bits with the current fuse bits.
   - Observable: consecutive reads show updated OR result with no modeled delay.

Notes:
- All behaviors are synchronous in the model (callbacks and handlers run immediately); tests should not rely on deferred timers.

---

## Test Case Scenarios (for Software Feature Validators)

| Scenario | Setup | Action | Expected Result | Verification Point |
|---------:|-------|--------|-----------------|--------------------|
| 1. Resolved IP-disable read | Instantiate device in Simics; set software register (cr_reg) to 0x00000010; set fuses_reg to 0x00000001 | Read sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 | Returned DWORD == 0x00000011 (0x10 | 0x1) | Compare read value to expected OR |
| 2. PUF-ready causes outputs | Connect puf_ip_ready port to a test driver; attach signal monitors/HAPs to puf_rst_b and hwrs_mc_pstate | Test driver issues signal_raise on puf_ip_ready | Device internal level updated; puf_rst_b and/or hwrs_mc_pstate change state (driven) | Observe signal monitors/HAP callbacks on CONNECTs detect level change |
| 3. Strap attribute update | Load model; ensure strap_txt_plten initially X (or undefined) | Set strap_txt_plten attribute to 0x5 via Simics configure/set-attribute | get(strap_txt_plten) returns 0x5 | Attribute getter returns new value |
| 4. Software register write reflected immediately | Set fuses_reg to 0x0; set software cr_reg to 0x0; read resolved register -> expect 0x0. Then write cr_reg to 0xA. | Read resolved register | First read 0x0, second read 0xA | Observed read values match expected before and after register write |
| 5. PUF de-assert updates outputs | Connect puf_ip_ready and attach monitors; assert puf_ip_ready then de-assert after verify | signal_raise, then signal_lower on puf_ip_ready | Monitors observe assert-driven outputs and subsequent de-assert-driven changes | Monitor logs/HAPs record both transitions |

Test guidance:
- Use model attribute access or dedicated helper APIs to set cr_reg and fuses_reg as required by the test framework.
- Attach HAPs or Simics signal monitors to c_pin_out instances to capture driven output transitions.
- Tests should not assume timing delays; changes are synchronous within callbacks.

Source: *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*

---

## Implementation Notes (for Simics Device Model Developers)

- Primary DML source:
  - srv-pm/code/hwrs-gen2/hwrs-straps.dml — contains the DML nodes that implement this capability (register, ports, attributes, and pin outputs).
  - *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*

- Template dependencies and key templates:
  - ip_disable_resolved_cr_reg — provides read_register callback logic for sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3.
  - pin_state_notifier — implements port behavior for puf_ip_ready (on-change handlers, internal level update).
  - c_pin_out / c_pin_out_hap — used to expose and drive CONNECT outputs (puf_rst_b, hwrs_mc_pstate, scu_start_pmsync_handshake).
  - uint64_attr — used to expose strap_txt_plten and strap_txt_agent attributes.

- Inheritance chain:
  - c_pin_out typically inherits c_pin_out_hap behavior; ip_disable_resolved_cr_reg is a specialized register template with a read callback; pin_state_notifier encapsulates port-level on-change logic.

- Extension and override points:
  - Read callback: ip_disable_resolved_cr_reg.read_register is the primary point to alter resolved register behavior. Override or extend the callback to add extra side-effects or additional OR-logic.
  - PUF change handler: the device-level handler invoked by pin_state_notifier can be overridden in device C/UML code to implement different drive patterns, timing, or additional checks.
  - c_pin_out drives: device code that calls into the c_pin_out instances decides which CONNECTs are asserted and when — extend device behavior by adding additional logic or conditions before invoking the c_pin_out methods.
  - Strap attribute setters/getters: uint64_attr can be extended with validation or additional side-effects (e.g., signal toggles on particular strap values).

- Implementation notes / internal names:
  - Software-backed register referenced as cr_reg; hardware fuses referenced as fuses_reg in model code. The resolved read returns cr_reg.val | fuses_reg.val.
  - The PUF readiness port uses the pin_state_notifier on-change handler to set an internal level and then calls device change handlers.

- Simulation fidelity:
  - Accurate: resolved register read returns OR of software and fuse bits; input port invocation and driven outputs behave in an event-callback consistent manner.
  - Limited/Not-modeled: no timing delays, no multi-cycle hardware FSMs or handshake sequencing modeled, no modeled internal side-effects beyond immediate callback behavior, and no modeled register write side-effects other than attribute storage.
  - Tests relying on hardware timing or multi-step hardware sequences must be adapted or augmented in the simulation (e.g., add explicit delays in device override handlers where timing matters).

---

## Platform Integration Notes (for Platform Architects)

- Role in platform:
  - Provides a lightweight HWRS-related capability to coordinate PUF readiness, strap configuration, and expose a resolved IP-disable register to software in the platform Simics configuration.
  - Acts as the HWRS/IMH hardware abstraction that other platform components (PUF model, memory controller, SCU/PM domain) interact with through PORT/CONNECT interfaces.

- Required PORT/CONNECT signal connections and counterparts:
  - puf_ip_ready (PORT) must be connected to the PUF model or a test stimulus component that asserts readiness via signal_raise/signal_lower.
  - puf_rst_b (CONNECT) should be connected to the reset input of the PUF or reset domain consumer (or a test monitor).
  - hwrs_mc_pstate (CONNECT) should be connected to the memory controller power/state handling model.
  - scu_start_pmsync_handshake (CONNECT) should connect to the SCU or other PM synchronization consumer implementing the handshake.
  - The model’s fuses_reg and cr_reg backing the resolved IP-disable read must either be present in this device or mapped to the platform’s fuse/register model so that platform-level fuse programming is visible to this device.

- Dependencies:
  - PUF model (or signal-driver) for puf_ip_ready stimulus.
  - Fuse/model providing fuses_reg values used by resolved register reads.
  - Platform-level configuration system that sets strap attributes (strap_txt_plten, strap_txt_agent) during platform configuration or bring-up.

- Configuration parameters affecting behavior:
  - strap_txt_plten (uint64 attribute) — platform configuration determines the value; affects software-visible strap state.
  - strap_txt_agent (uint64 attribute) — platform configuration determines agent-related strap state.
  - Software register backing the resolved ip-disable value (cr_reg) — can be initialized/modified by platform scripts or device initialization code.
  - Fuse register (fuses_reg) — should be initialized by platform fuse model or left at default if not present.

- Integration guidance:
  - Ensure connectors are assigned in platform topologies so that puf_ip_ready is driven by the intended source (PUF, test harness).
  - If platform power or reset domains require specific timing, consider extending the device’s change handlers to emulate the required delays or add explicit Simics events.
  - Validate strap attribute propagation in platform automation scripts to ensure consistent configuration across reboots or model reloads.

Source: *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml*

---

If you need example Simics commands (attribute get/set, attaching HAPs, asserting ports) or a template-based patch showing how to override the read_register or change handler to add timing behavior, I can provide those code snippets and command sequences.