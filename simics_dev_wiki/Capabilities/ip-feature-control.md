[← Device Overview](overview.md)

---

# ip-feature-control — HWRS IP-disable & sequencer feature-control (dmr_imh_hwrs_fv)

Overview
--------
This capability models the HWRS (Hardware Reset/Sequencer) IP-disable and sequencer-driven feature-control behavior for the dmr_imh_hwrs_fv device. It provides:

- Per-DWORD permanent fuse/storage attributes (ip_disable_fuses_dword0..9, sku_feature_dword4, etc.) that represent one-time-programmed or static configuration bits.
- Resolved read-only registers (sb_cr.IP_DISABLE_RESOLVED_CR_DWORD*) that return the bitwise OR of software-controlled control-register values and the fuse DWORDs, exposing the effective disable masks visible to software.
- Sequencer control via sb_cr.HWRS_SEQ_CONTROL, including write-side effects that drive external outputs (yyDIE_ENABLEx, HWRS_WAIT_PINS_PHASE_3_1) and apply phase-specific disables (e.g., Phase-4 HAMVF/PCIe groups).
- Input and output signal ports implemented with pin_state_notifier / port_state_notifier semantics for IP-ready and configuration-ack handshake (scu_config_ack, puf_ip_ready, mdfc_ip_ready) and HWRS outputs (hwrs_mc_pstate, yyDIE_ENABLEx, etc.).

Scope: The simulation models register read/write semantics (including resolved RO reads), saved fuse/feature attributes, sequencer control writes and their immediate side-effects, and signal-port change handlers that may advance the internal sequencer. Timing is modeled as level-held signals and immediate handler-driven state changes; no explicit real-time timers are provided for delayed hardware timing unless implemented elsewhere in the reset-sequencer FSM templates. Stubbed: low-level electrical timing, analog behavior, and any undocumented/opaque microcode within a hardware sequencer are not modeled beyond the observable register and signal behaviors. Source: srv-pm/code/hwrs-gen2/* and srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/* (see Implementation Notes).

How It's Simulated
-------------------
Simulation constructs used

- DML Registers: The sb_cr register bank exposes:
  - Read-only resolved registers: IP_DISABLE_RESOLVED_CR_DWORD0..9 (examples: DWORD1, DWORD2, DWORD4, DWORD5, DWORD6, DWORD7, DWORD8). These registers implement a custom getter that returns cr_reg.val | fuses_reg.val (resolved mask). *Source: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml*
  - Read/Write control register: sb_cr.HWRS_SEQ_CONTROL. Writes to this register have an after_write/write-callback that inspects fields (e.g., Imh_Disable_Programming_Done), drives outputs (yyDIE_ENABLEx), mirrors values to HWRS_WAIT_PINS_PHASE_3_1, and applies phase-specific disables. *Source: srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml / reg-banks-impl.dml*

- Saved Attributes: Permanent fuse values and runtime configuration are modeled as saved attributes:
  - uint64_attr: ip_disable_fuses_dword0..9, sku_feature_dword4, etc.
  - bool_attr / strap_attr_u64: d2d_ip_disable, trigger_cold_rst_exit_done, etc.
  These attributes are read by resolved-register getters and by device logic when composing effective masks. *Source: srv-pm/code/hwrs-gen2/attributes.dml / hwrs-straps.dml*

- Signal Ports (pin_state_notifier / port_state_notifier): Inputs (mdfc_ip_ready, puf_ip_ready, scu_config_ack) and outputs (hwrs_mc_pstate, yyDIE_ENABLEx, HWRS_WAIT_PINS_PHASE_3_1) are modeled via port/pin notifiers. Input assertions invoke change handlers that update internal port level state and may trigger sequencer progression logic. Output signals are driven by register write handlers or internal state transitions. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml / hwrs-ip-disable.dml*

- FSM/Sequencer: The device implements sequencer state/logic via reset-sequencer-fsm and associated templates (reset-sequencer-fsm.dml, resetbus.dml). Sequencer waits for target inputs (scu_config_ack, other IP-ready signals) and advances when conditions are met. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*

Stubbed or abstracted elements

- No low-level timing model for electrical rise/fall delays beyond immediate handler invocation and level-held semantics.
- Internal micro-architectural sequencing that does not expose register or port-visible effects is not modeled.

Working Flow
------------
High-level flows and sequences implemented by the model:

Flow: phase-3-disable-apply
- Trigger: CPU/software writes to sb_cr.HWRS_SEQ_CONTROL.
- Steps:
  1. The HWRS_SEQ_CONTROL write handler (after_write) runs and inspects Imh_Disable_Programming_Done and related fields.
  2. It drives external outputs yyDIE_ENABLEx according to the CBB fuse-disable state and the values written.
  3. It mirrors control bits into HWRS_WAIT_PINS_PHASE_3_1 outputs.
  4. It applies Phase-4 IP disables for defined groups (HAMVF/PCIe) by updating internal state or driving outputs.
- Observable results: yyDIE_ENABLEx and HWRS_WAIT_PINS_PHASE_3_1 output levels change; subsequent reads of sb_cr.IP_DISABLE_RESOLVED_CR_DWORD* reflect the resolved masks (cr_reg.val | fuses_reg.val). *Source: hwrs-ip-disable.dml, reg-banks-impl.dml*

Flow: sequencer-wait-for-scu-ack
- Trigger: External assertion of scu_config_ack input port.
- Steps:
  1. scu_config_ack pin_state_notifier fires; device change handler records new level.
  2. The handler checks whether the internal sequencer is in a WAIT state and whether the current wait target is the SCU.
  3. If matched, sequencer advances (the handler updates internal state and may invoke side-effects already implemented in sequencer transition handlers).
- Observable results: Sequencer progression becomes visible via HWRS outputs or register state changes (e.g., further HWRS_SEQ_CONTROL-driven outputs). *Source: reset-sequencer-fsm.dml / hwrs-ip-disable.dml*

Register semantics and side-effects
- Resolved RO registers (IP_DISABLE_RESOLVED_CR_DWORD*): reads return (cr_reg.val | fuses_reg.val) via a get() override; writes are discarded (osdml_read_only). Example: sb_cr.IP_DISABLE_RESOLVED_CR_DWORD6.get() returns cr_reg.val | fuses_reg.val. *Source: dmr_imh_b0_hwrs_fv_regs.dml*
- HWRS_SEQ_CONTROL (RW): normal reads return current register state. Writes run a handler that may drive outputs and update internal sequencer/control state. *Source: hwrs-ip-disable.dml*

Interface signals and conditions
- Inputs:
  - scu_config_ack: triggers sequencer advancement when the sequencer is waiting on the SCU. Implemented via pin_state_notifier. *Source: dmr_imh_b0_hwrs_fv_regs.dml*
  - puf_ip_ready, mdfc_ip_ready: IP-ready notifications; change handlers update internal status and can satisfy sequencer wait conditions. *Source: dmr_imh_b0_hwrs_fv_regs.dml*
- Outputs:
  - hwrs_mc_pstate: pstate signal to memory controller; driven by HWRS logic (sequencer/control writes). Level-held until changed. *Source: dmr_imh_b0_hwrs_fv_regs.dml*
  - yyDIE_ENABLEx, HWRS_WAIT_PINS_PHASE_3_1: driven by HWRS_SEQ_CONTROL write handler. *Source: hwrs-ip-disable.dml*

Event scheduling
- No explicit deferred timers are documented in the provided chunks. Sequencer progression is driven by register writes and immediate port change handlers. Where the reset-sequencer-fsm template implements deferred transitions, refer to reset-sequencer-fsm.dml for details. *Source: reset-sequencer-fsm.dml*

Register Map
------------
| Register | Bank | Access Type | Reset Value | Write Side-Effect | Read Side-Effect |
|----------|------|-------------|-------------|-------------------|------------------|
| IP_DISABLE_RESOLVED_CR_DWORD1 | sb_cr | RO | n/a | Writes ignored (osdml_read_only) | Returns cr_reg.val | fuses_reg.val (resolved mask) — includes Sca_Disable and other Phase‑3 bits. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| IP_DISABLE_RESOLVED_CR_DWORD2 | sb_cr | RO | n/a | Writes ignored | Returns cr_reg.val | fuses_reg.val — includes Llc_Disable [39:0], Hsf_Disable bits and Phase‑2 masks. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| IP_DISABLE_RESOLVED_CR_DWORD4 | sb_cr | RO | n/a | Writes ignored | Returns cr_reg.val | fuses_reg.val — Io_Stack_Disable [15:8], Mc_Stack_Disable etc. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| IP_DISABLE_RESOLVED_CR_DWORD5 | sb_cr | RO | n/a | Writes ignored | Returns cr_reg.val | fuses_reg.val — Spare_Disable [63:0]. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| IP_DISABLE_RESOLVED_CR_DWORD6 | sb_cr | RO | n/a | Writes ignored | Returns cr_reg.val | fuses_reg.val — Core_Disable [59:0] resolved mask. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| IP_DISABLE_RESOLVED_CR_DWORD7 | sb_cr | RO | n/a | Writes ignored | Returns cr_reg.val | fuses_reg.val — Ip_Disable [63:0]. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| IP_DISABLE_RESOLVED_CR_DWORD8 | sb_cr | RO | n/a | Writes ignored | Returns cr_reg.val | fuses_reg.val — Ip_Disable [63:0]. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| HWRS_SEQ_CONTROL | sb_cr | RW | n/a | Write handler inspects Imh_Disable_Programming_Done and related fields; drives yyDIE_ENABLEx; mirrors to HWRS_WAIT_PINS_PHASE_3_1; applies Phase‑4 IP disables for HAMVF/PCIe groups; updates internal control state. *Source: hwrs-ip-disable.dml* | Read returns current control-state register value. *Source: hwrs-ip-disable.dml* |

Note: Reset values are not provided in the available code chunks; consult the register definition DML files for canonical reset values. *Source: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml*

Interface Signals
-----------------
| Signal | Direction | Interface Type | Trigger Condition | Action |
|--------|-----------|----------------|-------------------|--------|
| hwrs_mc_pstate | OUT (CONNECT) | signal | Driven by sequencer/control logic (e.g., HWRS_SEQ_CONTROL write or sequencer transitions) | Drives downstream memory-controller pstate request; level-held until changed. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| yyDIE_ENABLEx | OUT | signal | HWRS_SEQ_CONTROL write after_write inspects Imh_Disable_Programming_Done and fuse state | Output levels driven to indicate IP die-enable status; observable externally. *Source: hwrs-ip-disable.dml* |
| HWRS_WAIT_PINS_PHASE_3_1 | OUT | signal | HWRS_SEQ_CONTROL write mirrors written wait bits | Used to indicate wait/pause conditions; used by external logic to acknowledge or proceed. *Source: hwrs-ip-disable.dml* |
| scu_config_ack | IN (PORT) | signal (pin_state_notifier) | External SCU asserts configuration-done | Device change handler checks sequencer WAIT state and matching wait-target; if matched, sequencer advances. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| puf_ip_ready | IN (PORT) | signal (pin_state_notifier) | External PUF asserts ready line | Change handler sets internal ready level and may satisfy sequencer waits. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| mdfc_ip_ready | IN (PORT) | signal (port_state_notifier) | External MDFC asserts ready line | Change handler updates internal state and may allow sequencer to proceed. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |

Behavioral Specification (for Software Feature Validators)
----------------------------------------------------------
Each statement is directly testable in Simics by controlling register writes and port signals; observables include register reads and driven output signal levels.

1. WHEN software reads any sb_cr.IP_DISABLE_RESOLVED_CR_DWORDn register -> THEN the returned 64-bit value equals (software CR register value bitwise-OR permanent fuse DWORD value). Verify: returned value == cr_reg.val | ip_disable_fuses_dwordn. *Source: dmr_imh_b0_hwrs_fv_regs.dml*

2. WHEN software writes sb_cr.HWRS_SEQ_CONTROL with Imh_Disable_Programming_Done=1 and specific yyDIE enable bits set -> THEN device's yyDIE_ENABLEx outputs are driven to reflect the written enable bits gated by CBB fuse-disable state, and HWRS_WAIT_PINS_PHASE_3_1 mirrors the written wait bits. Verify: observe output signals and subsequent resolved-register reads reflecting applied disables. *Source: hwrs-ip-disable.dml*

3. WHEN the device is in a sequencer WAIT state for SCU and external signal scu_config_ack is asserted -> THEN the sequencer advances and any sequencer-driven outputs or register-state transitions triggered by advancement occur (e.g., new HWRS_SEQ_CONTROL side-effects or next-phase outputs). Verify: sequencer state-change viewable via registers or outputs; subsequent actions occur. *Source: reset-sequencer-fsm.dml*

4. WHEN an IP ready input (puf_ip_ready or mdfc_ip_ready) asserts while the sequencer is waiting for that IP -> THEN the device records the ready condition and, if it was the awaited condition, advances the sequencer. Verify: internal ready flag reflected in device state (via debug/register view) and sequencer progression observable. *Source: dmr_imh_b0_hwrs_fv_regs.dml*

5. WHEN software attempts to write any IP_DISABLE_RESOLVED_CR_DWORD* register -> THEN the write is ignored and the register read-back remains the resolved fuse|CR value. Verify: write completes (no error) but read returns same resolved value as before. *Source: dmr_imh_b0_hwrs_fv_regs.dml*

Test Case Scenarios (for Software Feature Validators)
----------------------------------------------------
| Scenario | Setup | Action | Expected Result | Verification Point |
|---------|-------|--------|-----------------|--------------------|
| Resolved read returns OR of CR and fuses | Configure device attribute ip_disable_fuses_dword6 = 0x0000_0001_0000 ; write CR equivalent register for DWORD6 with value 0x2 | Read sb_cr.IP_DISABLE_RESOLVED_CR_DWORD6 | Read returns 0x0000_0001_0002 (fuse OR CR) | Compare read value to (fuse | CR) read via debug view or API. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| HWRS_SEQ_CONTROL drives outputs and applies disables | Set CBB fuse-disable state so certain bits are masked; write HWRS_SEQ_CONTROL with Imh_Disable_Programming_Done=1 and yyDIE bits = mask X | Observe yyDIE_ENABLEx and HWRS_WAIT_PINS_PHASE_3_1; read resolved IP_DISABLE registers | yyDIE_ENABLEx outputs reflect (written bits & ~fuse_mask); HWRS_WAIT_PINS_PHASE_3_1 equals mirrored bits; resolved registers reflect applied disables | Inspect output port levels and register readbacks. *Source: hwrs-ip-disable.dml* |
| Sequencer waits for SCU and advances on ack | Put sequencer into a WAIT state targeting SCU (via HWRS_SEQ_CONTROL or prior steps) | Assert scu_config_ack input port | Sequencer advances; next-phase outputs or register updates occur | Read sequencer state/registers and observe subsequent output changes. *Source: reset-sequencer-fsm.dml* |
| IP-ready input satisfies sequencer wait | Configure sequencer to wait for MDFC or PUF; ensure input is deasserted | Assert mdfc_ip_ready or puf_ip_ready port | Device records ready; sequencer advances if target matched | Observe internal ready bit (debug) and sequencer-driven outputs. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |
| Writes to resolved RO registers are ignored | Attempt to write sb_cr.IP_DISABLE_RESOLVED_CR_DWORD5 with non-zero value | Read sb_cr.IP_DISABLE_RESOLVED_CR_DWORD5 | Read remains cr_reg.val | fuses_reg.val and the write has no effect | Verify by comparing readback before/after write. *Source: dmr_imh_b0_hwrs_fv_regs.dml* |

Implementation Notes (for Simics Device Model Developers)
---------------------------------------------------------
Key DML source files
- srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml — core logic for HWRS IP-disable behavior and HWRS_SEQ_CONTROL write handler. *Source: code map*
- srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml — sb_cr register bank definitions and get() implementations for resolved registers. *Source: code map*
- srv-pm/code/hwrs-gen2/reg-banks-impl.dml — register bank implementation templates and common helpers. *Source: code map*
- srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml — sequencer state machine and wait/advance semantics. *Source: code map*
- srv-pm/code/hwrs-gen2/attributes.dml — attribute definitions for ip_disable_fuses_dword*, sku_feature_dword4, d2d_ip_disable, etc. *Source: code map*
- srv-pm/code/hwrs-gen2/hwrs-straps.dml — strap/strap-like attributes that influence behavior. *Source: code map*
- srv-pm/code/hwrs-gen2/hwrs-cbb-disable.dml — logic that gates controls with CBB fuse-disable state. *Source: code map*
- srv-pm/code/hwrs-gen2/resetbus.dml, pwrgd-reset-templates.dml — supporting reset and event templates referenced by sequencer. *Source: code map*

Template dependencies and implementation structure
- Resolved registers implement get() overrides that compute cr_reg.val | fuses_reg.val. These getters read the saved fuse attributes (ip_disable_fuses_dwordN) and the corresponding CR shadow register. Extend or override by replacing the get() implementation or by altering the attribute sources. *Source: dmr_imh_b0_hwrs_fv_regs.dml*
- HWRS_SEQ_CONTROL uses a write-callback/after_write hook that implements side-effects: driving outputs (yyDIE_ENABLEx, HWRS_WAIT_PINS_PHASE_3_1), applying phase-specific disable rules (HAMVF/PCIe), and updating internal sequencer/control state. Hook location: hwrs-ip-disable.dml / reg-banks-impl.dml.
- Sequencer behavior and wait/ack handshake are implemented via reset-sequencer-fsm template. Port change handlers (pin_state_notifier/port_state_notifier) are registered on input ports to call the FSM check/advance logic.

Extension/override points
- To change resolved behavior: override the register get() or change the attribute read sources (e.g., read additional mask sources).
- To change write side-effects: modify the HWRS_SEQ_CONTROL after_write handler or add callbacks to the sequencer FSM transitions.
- To add additional inputs/outputs: add new pin/port definitions in the device DML and implement notifier handlers that integrate with the sequencer FSM.
- To add timing/delays: extend FSM templates to schedule events (e.g., using event schedulers) instead of making immediate transitions in handlers.

Saved attributes and state to be aware of
- ip_disable_fuses_dword0..9 (uint64_attr): permanent fused disable masks read by resolved registers. *Source: attributes.dml*
- sku_feature_dword4 (uint64_attr): SKU feature mask used by gating logic. *Source: attributes.dml*
- d2d_ip_disable (bool_attr), trigger_cold_rst_exit_done (bool/strap): used by sequencer/reset logic. *Source: attributes.dml*
- Internal sequencer state variables and wait-target bookkeeping (internal to reset-sequencer-fsm.dml). *Source: reset-sequencer-fsm.dml*

Simulation fidelity and known differences
- The model exposes the register and port-visible functional behavior required by software validation (resolved masks, sequencer handshake, outputs). It does not model microsecond/nanosecond electrical timing or analog characteristics. Sequencer transitions are immediate upon matching conditions unless the FSM template inserts explicit delays. Consult reset-sequencer-fsm.dml for any delay semantics implemented. *Source: reset-sequencer-fsm.dml*

Platform Integration Notes (for Platform Architects)
----------------------------------------------------
Role in platform
- dmr_imh_hwrs_fv acts as the HWRS controller for the IMH device; it authoritatively applies permanent fuse masks and software CR masks to present resolved IP-disable state to firmware/software and to drive die-level enable signals and wait pins used during reset/configuration flows.

Required signal connections (minimum)
- Inputs (must be connected to their logical sources):
  - scu_config_ack <- SCU configuration logic (must assert to acknowledge SCU-targeted waits). *Source: dmr_imh_b0_hwrs_fv_regs.dml*
  - puf_ip_ready <- PUF IP ready output (connected to PUF model). *Source: dmr_imh_b0_hwrs_fv_regs.dml*
  - mdfc_ip_ready <- MDFC IP ready output (connected to MDFC model). *Source: dmr_imh_b0_hwrs_fv_regs.dml*
- Outputs (device drives these to other platform components):
  - hwrs_mc_pstate -> downstream memory-controller pstate handler. *Source: dmr_imh_b0_hwrs_fv_regs.dml*
  - yyDIE_ENABLEx -> downstream die/port enables; used to disable/enable IPs at die granularity. *Source: hwrs-ip-disable.dml*
  - HWRS_WAIT_PINS_PHASE_3_1 -> external wait pins used to coordinate phase-3 sequencing. *Source: hwrs-ip-disable.dml*

Dependencies on other capabilities
- SCU (System Configuration Unit): sequencer waits may require SCU ack for progression.
- PUF, MDFC and other IPs that assert IP-ready lines to clear sequencer waits.
- CBB fuse/config logic: HWRS write-handling is gated by CBB fuse-disable information. *Source: hwrs-cbb-disable.dml*
- Reset bus / power-good infrastructure (pwrgd-reset-templates.dml) is used to coordinate reset flows.

Configuration parameters that affect behavior
- ip_disable_fuses_dword0..9 (uint64_attr) — permanent fused disable masks applied to resolved registers. *Source: attributes.dml*
- sku_feature_dword4 (uint64_attr) — SKU-level features used in gating. *Source: attributes.dml*
- d2d_ip_disable (bool_attr) — configure die-to-die IP disable handling. *Source: attributes.dml*
- trigger_cold_rst_exit_done (bool/strap) — may affect reset/exit sequencing. *Source: attributes.dml*

Integration guidance
- Ensure that SCU, PUF, MDFC, and memory-controller models are connected to the HWRS ports so that sequencer waits and pstate outputs can be exercised in platform-level tests.
- Configure fuse attributes at device instantiation time to represent the target hardware SKU and fuse-programming state; these attributes determine resolved disable masks visible to firmware.
- For platform bring-up tests, use HWRS_SEQ_CONTROL writes combined with asserting input ack/ready signals to validate phase transitions and correct external signal driving.

References
----------
- DML implementation and register definitions: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml (resolved-register get() implementations). *Source: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml*
- HWRS IP-disable & HWRS_SEQ_CONTROL logic: srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml; srv-pm/code/hwrs-gen2/reg-banks-impl.dml. *Source: srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml; srv-pm/code/hwrs-gen2/reg-banks-impl.dml*
- Sequencer FSM: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*
- Attributes, straps and CBB disable logic: srv-pm/code/hwrs-gen2/attributes.dml; srv-pm/code/hwrs-gen2/hwrs-straps.dml; srv-pm/code/hwrs-gen2/hwrs-cbb-disable.dml. *Source: srv-pm/code/hwrs-gen2/*

If you want, I can:
- Produce concrete Simics TCL/Python test scripts exercising the scenarios above.
- Extract the exact register names and field offsets for CR shadow registers to make validation scripts exact.