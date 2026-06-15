[← Device Overview](overview.md)

---

# die-topology-and-die-synchronization

Overview
--------
This capability models IMH (integrated management hub) hardware-reset sequencing, die-topology sampling (strap/config attributes) and die-to-die (D2D) synchronization handshakes used to coordinate reset/enable across CBB/IMH dies. The model is part of the dmr_imh_hwrs_fv device (functional verification model) and exposes:
- saved strap/config attributes for per-die identifiers and SKU/topology bits (die_id, die_hvm, svid_not_present, lg_spare_*), and a configured maximum number of CBBs per IMH (max_cbb_num_per_imh); these are bound to HWRS die-config register fields.  
- resolved IP-disable read semantics: resolved IP-disable registers return the logical OR of software CRs and fuses to present the authoritative snapshot.  
- a reset sequencer that advances through phases and drives yyDIE_ENABLE outputs and xxREFCLK_Rdy as sequencing progresses.  
- IMH↔CBB and IMH↔IMH hardware-sync request/ack handshake behavior (gather/quorum and role-gated ACK handling).  

Scope: the model implements functional behavior required for feature validation and platform sequencing (sequencer FSM, timing via infra_timer, strap forwarding, read-resolved semantics). Physical analog details (electrical line capacitance, analog timing jitter) are not modeled. Timing is implemented with configurable delays (didt_timeout_us, per-phase constants) rather than transistor-level timing. *Source: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml; srv-pm/code/hwrs-gen2/hwrs-timer.dml*

How It's Simulated
------------------
- Registers: implemented via register bindings, write callbacks and read_register overrides. Key registers include sb_cr.HWRS_SEQ_CONTROL (write callback), SKU_FEATURE_DWORD0 (write setter forwarding strap), and IP_DISABLE_RESOLVED_CR_DWORD0/1 (read override that returns cr_reg | fuses_reg). Read/write side-effects implement mirrored outputs and resolved snapshots. *Source: srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml; srv-pm/bt/.../dmr_imh_b0_hwrs_fv_regs.dml*

- Attributes / straps: strap_attr_u64, uint64_attr and bool_attr values are bound to register fields via reg_fld_binding and exposed via attribute getters. These model board/package straps (die_hvm, svid_not_present, lg_spare_*). *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml; srv-pm/code/hwrs-gen2/attributes.dml*

- Sequencer FSM: driven by register writes and timer expiries. The reset-sequencer FSM is implemented in reset-sequencer-fsm.dml and advanced by specific write callbacks (e.g., Imh_Disable_Programming_Done) or timer phases. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*

- Events / timers: a retriggerable infra_timer implements a four-phase one-shot chain initiated when PLTRST_B de-asserts; each expiry posts the next phase and applies didt_timeout_us delays to model DIDT staggering and pre-reset actions. *Source: srv-pm/code/hwrs-gen2/hwrs-timer.dml*

- I/O interfaces: outputs are driven via c_pin_out / c_pin_out_hap templates for die-enable pins (yyDIE_ENABLE0..3) and hw-sync lines; inputs are implemented as ports with on_change handlers (imh2cbb_hwsync_req_in, imh2imh_hwsync_req_in, imh2imh_hwsync_ack_in, pltrstb_input, scu_config_ack). Handlers implement level tracking and gating logic (primary vs secondary IMH). *Source: srv-pm/code/hwrs-gen2/hwsync-d2d.dml; srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml*

- Stubbed / approximated behavior: analog and electrical aspects of straps and signals are not modeled. Timing is coarse-grained using configurable delays (didt_timeout_us and phase constants) rather than cycle-accurate analog timing. Some platform-specific fuse write prevention behavior is guarded by flags (prevent_fuse_write_svid_not_present) and not enforced externally. Read/write side-effects are functional rather than cycle-accurate.

Working Flow
------------
This section describes the principal flows implemented in the model, the state machine interactions, register semantics, interfaces and event scheduling.

1) Warm-reset entry and DIDT staggering (FLOW: didt-warm-reset-entry)
- Stimulus: PLTRST_B de-assert (input port change).
- Handler: pltrstb_input.on_change calls do_pm_unwind() and arms the infra_timer first phase. *Source: srv-pm/code/hwrs-gen2/hwrs-timer.dml*
- infra_timer behavior: a retriggerable one-shot chain with four phases. Each infra_timer expiry posts the next phase and executes preamble/unwind actions; DIDT staggering delays between dies are implemented using didt_timeout_us in the per-phase after-handler. Final phase releases the reset-sequencer to continue toward BCLK-ready wait states.
- Observables: infra_timer phases executed in sequence; PM-unwind raised; DIDT staggering intervals observed before sequencer continues.

2) Die-enable programming (FLOW: die-enable-programming)
- Stimulus: Software writes sb_cr.HWRS_SEQ_CONTROL.Imh_Disable_Programming_Done.
- Write callback: HWRS_SEQ_CONTROL after_write mirrors Imh_Disable_Programming_Done into yyDIE_ENABLEx outputs (via c_pin_out) according to per-CBB fuse-disable state and writes HWRS_WAIT_PINS_PHASE_3_1. It may also apply Phase-4 IP disables for HAMVF/PCIe groups, assert xxREFCLK_Rdy and conditionally advance the reset-sequencer FSM toward the BCLK-ready wait target. Break_On_Index_Valid field controls sequencer breakpoint behavior (writing 1→0 removes breakpoint and may defer advance). *Source: srv-pm/bt/.../dmr_imh_b0_hwrs_fv_regs.dml; srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*
- Observables: yyDIE_ENABLE0..3 driven asserted/deasserted; HWRS sequencer state may progress; xxREFCLK_Rdy asserted when target reached.

3) IMH-to-CBB / IMH-to-IMH hardware sync handshake (FLOW: imh-to-cbb/imh-handshake)
- Stimulus: External assertion on imh2cbb_hwsync_req_in or imh2imh_hwsync_req_in input ports.
- Handler: on_change detects assertion, evaluates gather/quorum functions (e.g., all_imh2cbb_hwsync_req_is_asserted()). When quorum satisfied, model asserts corresponding outputs (imh2cbb_hwsync_req_out/imh2imh_hwsync_req_out) or replies with ack outputs per sequencer/role logic.
- Role gating: Some ACK handling is only executed on non-primary IMH instances (is_primary_imh gating). Duplicate transitions suppressed via internal level tracking.
- Observables: handshake outputs toggled, sequencer or handshake state advanced.

Registers Involved and Read/Write Semantics
- sb_cr.HWRS_SEQ_CONTROL (RW) — fields: Imh_Disable_Programming_Done, Break_On_Index_Valid. Write side-effects: Imh_Disable_Programming_Done mirrored to yyDIE_ENABLEx, updates HWRS_WAIT_PINS_PHASE_3_1, applies Phase-4 IP disables, can advance sequencer and assert xxREFCLK_Rdy. Break_On_Index_Valid 1→0 removes a sequencer breakpoint. No special read-side effect. *Source: srv-pm/bt/.../dmr_imh_b0_hwrs_fv_regs.dml*
- sb_cr.SKU_FEATURE_DWORD0 (RW) — field Svid_Not_Present. Write setter forwards strap into HWRS_DIE_CONFIG.Svid_Not_Present unless prevented. Read returns stored strap/fuse values. *Source: srv-pm/bt/.../dmr_imh_b0_hwrs_fv_regs.dml*
- sb_cr.IP_DISABLE_RESOLVED_CR_DWORD0/1 (RO) — read_register override returns cr_reg.val | fuses_reg.val (bitwise OR) to present resolved IP-disable snapshot. Writes have no effect. *Source: srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml*

Event Scheduling
- infra_timer: retriggerable one-shot chain of four phases. Initiated on PLTRST_B de-assert. Delays per-phase are sourced from didt_timeout_us and other phase constants. Each expiry posts the next phase and performs DIDT staggering and pre-reset actions (punit_pm_unwind, preamble). The chain proceeds unless canceled by other handlers/device reset. *Source: srv-pm/code/hwrs-gen2/hwrs-timer.dml*

Register Map
| Register | Bank | Access Type | Reset Value | Write Side-Effect | Read Side-Effect |
|----------|------|-------------|-------------|-------------------|------------------|
| sb_cr.HWRS_SEQ_CONTROL | sb_cr | RW | unspecified in model | Writing Imh_Disable_Programming_Done mirrors per-die Imh_Disable value to yyDIE_ENABLE[0..3] outputs, updates HWRS_WAIT_PINS_PHASE_3_1, applies Phase-4 IP disables, may advance reset-sequencer and assert xxREFCLK_Rdy. Break_On_Index_Valid 1→0 removes breakpoint. | Normal read of stored value (no extra side-effect). *Source: srv-pm/bt/.../dmr_imh_b0_hwrs_fv_regs.dml* |
| sb_cr.SKU_FEATURE_DWORD0 | sb_cr | RW | unspecified in model | Writing Svid_Not_Present commits value and forwards it into HWRS_DIE_CONFIG.Svid_Not_Present unless prevented by prevent_fuse_write_svid_not_present. | Returns stored strap/fuse initialization values. *Source: srv-pm/bt/.../dmr_imh_b0_hwrs_fv_regs.dml* |
| sb_cr.IP_DISABLE_RESOLVED_CR_DWORD0 | sb_cr | RO | n/a | Writes ignored (no hardware state change). | read_register returns cr_reg.val | fuses_reg.val (bitwise OR) to present resolved IP-disable snapshot. *Source: srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml* |
| sb_cr.IP_DISABLE_RESOLVED_CR_DWORD1 | sb_cr | RO | n/a | Writes ignored. | read_register returns cr_reg.val | fuses_reg.val (bitwise OR). Contains Sca_Disable and other resolved bits. *Source: srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml* |

Interface Signals
| Signal | Direction | Interface Type | Trigger Condition | Action |
|--------|-----------|----------------|-------------------|--------|
| yyDIE_ENABLE0 | OUT (CONNECT) | signal (pwrgd_reset) | Driven by HWRS logic after Imh_Disable_Programming_Done write | Level-held die-enable output for die0; asserted/deasserted to enable/disable downstream die. *Source: srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml* |
| yyDIE_ENABLE1 | OUT (CONNECT) | signal | Driven by HWRS_SEQ_CONTROL writes | Level-held die-enable for die1. *Source: srv-pm/.../dmr_imh_b0_hwrs_fv_regs.dml* |
| yyDIE_ENABLE2 | OUT (CONNECT) | signal | Driven by HWRS_SEQ_CONTROL writes | Level-held die-enable for die2. *Source: srv-pm/.../dmr_imh_b0_hwrs_fv_regs.dml* |
| yyDIE_ENABLE3 | OUT (CONNECT) | signal | Driven by HWRS_SEQ_CONTROL writes | Level-held die-enable for die3. *Source: srv-pm/.../dmr_imh_b0_hwrs_fv_regs.dml* |
| imh2cbb_hwsync_req_in | IN (PORT) | signal | External IMH (or peer) asserts request toward CBB | on_change handler evaluates all_imh2cbb_hwsync_req_is_asserted() and triggers CBB-sync handshake logic; may assert imh2cbb_hwsync_req_out and/or ack. *Source: srv-pm/code/hwrs-gen2/hwsync-d2d.dml* |
| imh2imh_hwsync_req_in | IN (PORT) | signal | Peer IMH asserts IMH→IMH hw sync request | Handler applies gather/quorum check; when satisfied triggers handshake and sequencer transitions. *Source: srv-pm/code/hwrs-gen2/hwsync-d2d.dml* |
| imh2imh_hwsync_ack_in | IN (PORT) | signal | Peer IMH asserts IMH→IMH hw sync ACK | on rising edge handler is gated by !is_primary_imh and carries out ACK processing. Duplicates suppressed by level tracking. *Source: srv-pm/.../dmr_imh_b0_hwrs_fv_regs.dml* |
| pltrstb_input (PLTRST_B) | IN (PORT) | signal | PLTRST_B de-assert (raise false/low→high as configured) | on_change calls do_pm_unwind() and arms infra_timer first phase to start warm-reset entry sequencing. *Source: srv-pm/code/hwrs-gen2/hwrs-timer.dml* |
| scu_config_ack | IN (PORT) | signal | SCU asserts config ack | Input handled by on_change; used in sequencing/handshake integration. *Source: capability data above* |

Behavioral Specification (for Software Feature Validators)
----------------------------------------------------------
- WHEN software writes sb_cr.HWRS_SEQ_CONTROL.Imh_Disable_Programming_Done = 1 -> THEN yyDIE_ENABLE[n] pins are driven to mirror the per-CBB fuse-disable mask (asserted/deasserted per fuse state) and HWRS_WAIT_PINS_PHASE_3_1 is updated; sequencer may advance toward BCLK-ready and xxREFCLK_Rdy may be asserted. Observable: yyDIE_ENABLE signals change level and HWRS sequencer state progresses. *Source: sb_cr.HWRS_SEQ_CONTROL write callback description.*

- WHEN software reads sb_cr.IP_DISABLE_RESOLVED_CR_DWORD0 (or DWORD1) -> THEN returned value == (software_CR_register_value OR fuse_register_value) for that DWORD. Observable: read value contains bits set by either software writes or fuse initialization. *Source: read_register override description.*

- WHEN PLTRST_B is de-asserted (pltrstb_input on_change) -> THEN do_pm_unwind() is invoked and the infra_timer first phase is armed; subsequent infra_timer expiries post the next phases, causing PM-unwind, DIDT staggering delays (didt_timeout_us), and eventual release of the reset-sequencer to BCLK-ready wait. Observable: infra_timer phase callbacks fired in sequence; pm_unwind flag or indicator set; yyDIE_ENABLE changes only after DIDT staggering completes. *Source: FLOW didt-warm-reset-entry; infra_timer description.*

- WHEN imh2cbb_hwsync_req_in lines from all expected IMH sources are asserted (quorum reached) -> THEN model asserts imh2cbb_hwsync_req_out/acks as per sequencer role and advances handshake state. Observable: imh2cbb_hwsync_req_out/ack_out toggles and handshake state progressed. *Source: imh2cbb_hwsync_req_in description.*

- WHEN SKU_FEATURE_DWORD0.Svid_Not_Present is written -> THEN the write setter forwards the value to HWRS_DIE_CONFIG.Svid_Not_Present (unless prevent_fuse_write_svid_not_present is set) and subsequent reads of HWRS_DIE_CONFIG reflect the updated strap. Observable: HWRS_DIE_CONFIG.Svid_Not_Present readback shows the new value. *Source: SKU_FEATURE_DWORD0 setter description.*

Test Case Scenarios (for Software Feature Validators)
----------------------------------------------------
| Scenario | Setup | Action | Expected Result | Verification Point |
|---------|-------|--------|-----------------|--------------------|
| Die-enable programming mirrors per-CBB fuse mask | Device instantiated with known per-CBB fuse-disable values; sequencer in pre-enable state. | Write sb_cr.HWRS_SEQ_CONTROL.Imh_Disable_Programming_Done = 1. | yyDIE_ENABLE[0..3] values reflect the fuse-disable mask (individual pins asserted/deasserted accordingly); HWRS_WAIT_PINS_PHASE_3_1 updated. | Sample yyDIE_ENABLE signals; read HWRS_WAIT_PINS_PHASE_3_1 register. *Source: HWRS_SEQ_CONTROL write callback.* |
| Resolved IP-disable read returns fuse OR CR | Initialize fuse bits with known pattern; write complementary bits into CR registers. | Read sb_cr.IP_DISABLE_RESOLVED_CR_DWORD0 and DWORD1. | Readback equals bitwise OR of fuse pattern and CR writes. | Compare read value to computed OR(fuse_val, cr_written_val). *Source: IP_DISABLE_RESOLVED read_register override.* |
| PLTRST_B warm reset triggers DIDT staggering | Configure didt_timeout_us to small value and known number of die; ensure infra_timer is cleared. | De-assert PLTRST_B (simulate raise) | infra_timer first phase is armed; subsequent phases expire in order, each applying didt_timeout_us delays; final phase releases sequencer toward BCLK-ready. | Observe infra_timer callbacks via HAPs/logging; verify intervals between per-die enable events match didt_timeout_us sequencing. *Source: FLOW didt-warm-reset-entry; infra_timer description.* |
| IMH-to-IMH handshake with role gating | Two IMH instances configured (primary/non-primary). Arrange peer req_in assertions to meet quorum. | Assert imh2imh_hwsync_req_in externally for all expected sources. | The receiving non-primary IMH will run imh2imh_hwsync_ack_in handler and assert Ack Out only if role gating conditions met; primary will not run secondary-only ACK path. | Observe ack_out signal levels on respective IMHs and verify handler gating behavior. *Source: imh2imh_hwsync_ack_in description.* |
| SVID strap forwarding via SKU_FEATURE_DWORD0 | Device instantiated with prevent_fuse_write_svid_not_present = false. | Write SKU_FEATURE_DWORD0.Svid_Not_Present = 1. | HWRS_DIE_CONFIG.Svid_Not_Present readback equals 1 (strap forwarded). | Read HWRS_DIE_CONFIG.Svid_Not_Present register/attribute. *Source: SKU_FEATURE_DWORD0 setter description.* |

Implementation Notes (for Simics Device Model Developers)
---------------------------------------------------------
- Key DML files:
  - dmr_imh_b0_hwrs_fv_regs.dml — device register bank and register callbacks for the device. *Source: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml*
  - hwrs-ip-disable.dml — resolved IP-disable read logic. *Source: srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml*
  - reset-sequencer-fsm.dml — sequencer FSM implementation used to advance state. *Source: srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml*
  - hwrs-timer.dml — infra_timer and phase sequencing logic for DIDT staggering and PM-unwind. *Source: srv-pm/code/hwrs-gen2/hwrs-timer.dml*
  - hwrs-straps.dml / attributes.dml — strap and attribute definitions and reg_fld_binding usage. *Source: srv-pm/code/hwrs-gen2/hwrs-straps.dml; srv-pm/code/hwrs-gen2/attributes.dml*
  - hwsync-d2d.dml — IMH↔CBB/IMH handshake implementation. *Source: srv-pm/code/hwrs-gen2/hwsync-d2d.dml*
  - pwrgd-reset-templates.dml, hwrs-cbb-disable.dml, hwrs-timer.dml, resetbus.dml — supporting templates. *Source: srv-pm/code/hwrs-gen2/*

- Template dependencies and inheritance:
  - c_pin_out and c_pin_out_hap templates used to drive outputs (yyDIE_ENABLEx). *Source: pwrgd-reset-templates.dml*
  - Reg-field binding via reg_fld_binding connects strap_attr_u64/uint64_attr fields to register fields (HWRS_DIE_CONFIG.*). *Source: hwrs-straps.dml*
  - read_register override templates used for resolved read semantics (IP_DISABLE_RESOLVED_CR_*). *Source: hwrs-ip-disable.dml*
  - infra_timer uses retriggerable one-shot event template in hwrs-timer.dml.

- Extension / override points:
  - Write callbacks: HWRS_SEQ_CONTROL.after_write and SKU_FEATURE_DWORD0.Svid_Not_Present setter are explicit extension points; developers can add extra side-effects or gating here.
  - Read overrides: IP_DISABLE_RESOLVED_CR_* read_register handlers can be extended to include additional resolved sources.
  - infra_timer phases: phase handler functions are centralized in hwrs-timer.dml — to change DIDT staggers or add phases, modify phase callbacks and timing constants.
  - Strap/attribute binding: reg_fld_binding points can be adjusted to sample different strap bits or expose additional attrs; attribute getters can be extended for alternate sampling semantics.

- Simulation fidelity / known differences from silicon:
  - Timing is modeled using configurable delays (didt_timeout_us and phase constants) and is not transistor- or cycle-accurate. Real hardware analog effects (signal rise/fall slopes, cross-talk, metastability) are not modeled. *Source: hwrs-timer.dml description.*
  - Resolved IP-disable semantics are implemented as a bitwise OR of CR and fuse registers; this models functional resolution but may differ from hardware that performs additional validation/latency on certain bits. *Source: hwrs-ip-disable.dml*
  - Some fuse-write prevention behavior is modeled by guard flags (e.g., prevent_fuse_write_svid_not_present) but external enforcement may differ on real platforms.

Platform Integration Notes (for Platform Architects)
---------------------------------------------------
- Role in platform:
  - This device implements die-topology sampling and hardware reset coordination for an IMH instance; it is responsible for sequencing die enable outputs, presenting resolved IP-disable status to firmware, and mediating D2D synchronization handshakes required before release of clocks/resets to downstream dies. *Source: Overview & Working Flows.*

- Required signal connections:
  - PLTRST_B input port must be connected to the board-level POR/reset source to initiate warm-reset entry sequences. *Source: hwrs-timer.dml*
  - yyDIE_ENABLE0..3 outputs must be connected to downstream die enable inputs (CBB power/reset domain). These are c_pin_out CONNECT nodes in the model. *Source: pwrgd-reset-templates.dml*
  - imh2cbb_hwsync_req/_ack and imh2imh_hwsync_req/_ack ports must be wired to corresponding IMH/CBB peer devices to implement quorum/gather semantics. Primary/non-primary role must be defined in platform configuration to gate ACK handlers. *Source: hwsync-d2d.dml*
  - SCU/PU (scu_config_ack) connection is used in sequencing; ensure SCU counterpart is present in the platform. *Source: input list.*

- Dependencies on other capabilities:
  - Requires connected CBB and peer IMH devices (or test harness) to exercise handshake/gather paths.  
  - Firmware/BIOS or testbench must write HWRS_SEQ_CONTROL and SKU_FEATURE_DWORD0 registers to exercise die-enable programming and strap forwarding flows.  
  - Fuse/strap initialization values are set at device instantiation time (attributes) and influence behavior (svid_not_present, die_hvm, lg_spare_*). *Source: attributes.dml; hwrs-straps.dml*

- Configuration parameters that affect behavior:
  - max_cbb_num_per_imh (uint64_attr) — bounds topology logic for how many CBB dies can attach to the IMH. *Source: attributes.dml*
  - didt_timeout_us (uint64_attr) — governs DIDT staggering timeout used during warm-reset entry. Adjusting this directly changes inter-die stagger timing. *Source: hwrs-timer.dml*
  - lg_spare_tx_en_b_5_0, lg_spare_tx_value_5_0 (strap_attr_u64) — spare transmitter routing straps bound to HWRS_DIE_CONFIG. *Source: hwrs-straps.dml*
  - die_hvm, svid_not_present — straps/attributes that gate manufacturing-mode and SVID rail presence behavior. *Source: attributes.dml; dmr_imh_b0_hwrs_fv_regs.dml*

References
----------
- srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml — device register bindings and callbacks. *Source: code map*
- srv-pm/code/hwrs-gen2/hwrs-ip-disable.dml — resolved IP-disable read semantics. *Source: code map*
- srv-pm/code/hwrs-gen2/reset-sequencer-fsm.dml — sequencer FSM. *Source: code map*
- srv-pm/code/hwrs-gen2/hwrs-timer.dml — infra_timer and DIDT sequencing. *Source: code map*
- srv-pm/code/hwrs-gen2/hwsync-d2d.dml — IMH↔CBB/IMH handshake logic. *Source: code map*
- srv-pm/code/hwrs-gen2/hwrs-straps.dml and attributes.dml — strap and attribute bindings. *Source: code map*

(End of page)