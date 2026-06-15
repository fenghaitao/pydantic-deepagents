[← Device Overview](overview.md)

---

# device-identification-and-provisioning — dmr_imh_hwrs_fv

Overview
--------
This capability models the board/SKU provisioning and identification logic of the IMH HWRS function in early platform bring-up. It exposes strap-backed configuration values (board_id0..board_id4, strap_socket_id, strap_partition_id, strap_legacy, strap_single_dimm_mode_oem), SKU/fuse dwords (sku_feature_dword0..sku_feature_dword9, ip_disable_fuses_dword9) and a computed, authoritative "resolved IP-disable" register (sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3). The model also drives early-boot control outputs used during power sequencing (early_boot_prim_rst_b and scu_start_pmsync_handshake).

Scope — simulated vs. stubbed
- Simulated: strap / fuse storage as persistent attributes; register read-side synthesis of resolved IP-disable by OR-ing software and fuse words; generation of output signal transitions and HAP notifications for early-boot sequencing; strap-to-register bindings that make strap values visible to firmware.
- Stubbed / simplified: no FSM or timed state-machine that models complex asynchronous hardware timing beyond explicit modelled calls to signal_raise()/signal_lower(); write access to the resolved IP-disable register is discarded (reads synthesize value, writes have no effect); no input PORT interfaces are modeled for this capability.

Sources: srv-pm/code/hwrs-gen2/hwrs-straps.dml, srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml, srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml. *Source: [srv-pm/code/hwrs-gen2/hwrs-straps.dml]* *Source: [srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml]*

How It's Simulated
------------------
- Straps and fuses are represented as DML attributes:
  - strap_attr_u64 and uint64_attr fields provide saved values for strap_partition_id, strap_socket_id, board_id0..board_id4, sku_feature_dword0..9, ip_disable_fuses_dword9, etc. Accessors (get()/set()) are provided by the attribute templates. *Source: [srv-pm/code/hwrs-gen2/hwrs-straps.dml]*
- The resolved IP-disable register (sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3) is implemented from a register template (ip_disable_resolved_cr_reg). The read_register callback synthesizes the returned value as the bitwise OR of the software-controlled IP-disable register value and the fuse word(s). Reads therefore present the "resolved" state to software; writes are ignored by the template. *Source: [srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml]*
- Output signals early_boot_prim_rst_b and scu_start_pmsync_handshake are implemented as c_pin_out instances that inherit or use the c_pin_out_hap template. signal_raise()/signal_lower() drive the remote port and emit Simics HAP callbacks (grouped under pwrgd_reset for the primary reset). *Source: [srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml]*
- No device input PORTs are defined for this capability (no input signals are consumed by this model).

Working Flow
------------
Detailed flows and behavior, including participating registers and signals.

Flow: read-resolved-ip-disable
- Stimulus: software reads sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3.
- Internal behavior:
  1. The register read triggers the ip_disable_resolved_cr_reg.read_register callback.
  2. The callback obtains the software IP-disable control register value (cr_reg.val) and the fuse word(s) (fuses_reg.val) and returns cr_reg.val | fuses_reg.val (bitwise OR).
- Result: caller receives the resolved DWORD3. Fields documented in DWORD3 (e.g., I3c_Spd_Disable [58:55], Tam_Disable [44]) reflect the OR of software control and fuses. Reads are the authoritative source of resolved state; the template does not produce write side-effects. *Source: [srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml]*

Flow: early-boot-primary-reset-assertion
- Stimulus: platform early-boot sequence calls early_boot_prim_rst_b.signal_raise().
- Internal behavior:
  1. c_pin_out_hap signal_raise() drives the connected remote port (if present).
  2. A Simics HAP (pwrgd_reset-group) is emitted to allow test instrumentation to observe the transition.
- Result: the connected downstream component observes PRIM_RST_B asserted (active-low asserted), and a HAP is logged. *Source: [srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml]*

Flow: strap-provisioning-read-at-init
- Stimulus: firmware or platform code reads strap_partition_id / strap_socket_id or reads sb_cr.POC_STRAPS.Pid.
- Internal behavior:
  1. The strap attribute strap_partition_id (strap_attr_u64) returns its configured value via get().
  2. The attribute is bound via reg_fld_binding to sb_cr.POC_STRAPS.Pid, so register reads reflect the strap value.
- Result: firmware obtains partition/socket identity and can establish topology or partition-specific behavior. *Source: [srv-pm/code/hwrs-gen2/hwrs-straps.dml]*

Register Map
------------
| Register | Bank | Access Type | Reset Value | Write Side-Effect | Read Side-Effect |
|----------|------|-------------|-------------|-------------------|------------------|
| sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 | sb_cr | RO (presented as read-only; fields declared osdml_read_only) | 0x0 (init_val = 0x0 for many fields) | Writes are discarded / ignored (no write_register/after_write callback) | Read triggers ip_disable_resolved_cr_reg.read_register which returns (cr_reg.val | fuses_reg.val) — bitwise OR of software IP-disable control and fuse words; read returns resolved DWORD; fields such as I3c_Spd_Disable [58:55], Tam_Disable [44] reflect resolved state. *Source: [srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml]*

Interface Signals
-----------------
| Signal | Direction | Interface Type | Trigger Condition | Action |
|--------|-----------|----------------|-------------------|--------|
| early_boot_prim_rst_b | OUT (CONNECT) | signal (c_pin_out / c_pin_out_hap) | Model code calls early_boot_prim_rst_b.signal_raise() during early-boot power sequencing | Drives connected remote PRIM_RST_B port (active-low asserted) and emits a Simics HAP in the pwrgd_reset group for instrumentation; signal_lower() deasserts. *Source: [srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml]* |
| scu_start_pmsync_handshake | OUT (CONNECT) | signal (c_pin_out / c_pin_out_hap) | Model code calls scu_start_pmsync_handshake.signal_raise() to initiate PMsync handshake | Drives connected SCU PMsync input and emits HAP notifications; subsequent signal_lower() ends handshake. *Source: [srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml]* |

Behavioral Specification (for Software Feature Validators)
----------------------------------------------------------
Each statement is precise and testable.

1. WHEN software reads sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 -> THEN the returned 64-bit value equals (software_IP_disable_control_dword3 OR ip_disable_fuses_dword9), i.e., the bitwise OR of the software control register and the configured fuse dword(s). Verification: compare read value with known cr_reg.val and attribute ip_disable_fuses_dword9. *Source: [srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml]*

2. WHEN software writes any field of sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 -> THEN write has no effect on the read value (writes are discarded) and no Simics-side write callback is invoked. Verification: write a non-zero, then read back and observe resolved value remains as produced by OR of cr_reg and fuses. *Source: [srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml]*

3. WHEN platform code invokes early_boot_prim_rst_b.signal_raise() -> THEN the connected remote port observes PRIM_RST_B asserted (active-low) and a HAP in group pwrgd_reset is emitted. Verification: monitor the connected port value and subscribe to the pwrgd_reset HAP. *Source: [srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml]*

4. WHEN platform code invokes scu_start_pmsync_handshake.signal_raise() -> THEN the connected SCU port observes the asserted handshake signal and a HAP is generated; subsequent signal_lower() clears the handshake. Verification: monitor SCU port state and HAP callbacks. *Source: [srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml]*

5. WHEN strap_partition_id or strap_socket_id is configured prior to instantiation -> THEN reads of sb_cr.POC_STRAPS.Pid or attribute.get() return the configured value, enabling firmware to establish partition/socket identity. Verification: set attribute in model instantiation, start simulation, read register field and attribute. *Source: [srv-pm/code/hwrs-gen2/hwrs-straps.dml]*

Test Case Scenarios (for Software Feature Validators)
----------------------------------------------------
| Scenario | Setup | Action | Expected Result | Verification Point |
|----------|-------|--------|-----------------|--------------------|
| Resolved IP-disable reflects fuse OR | Instantiate model with ip_disable_fuses_dword9 = 0x0000_1000_0000 and write cr_reg.val = 0x0000_0000_1000 | Read sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3 | Returned value has both bits set (OR result) | Read value == (cr_reg.val | ip_disable_fuses_dword9) |
| Writes to resolved register are ignored | Ensure cr_reg.val = 0x0 and ip_disable_fuses_dword9 = 0x0 | SW writes 0xFFFF_FFFF_FFFF_FFFF to sb_cr.IP_DISABLE_RESOLVED_CR_DWORD3, then read | Read returns 0x0 (or OR of configured fuse & control), not the written pattern | Read value unchanged after write |
| early_boot_prim_rst_b drives downstream PRIM_RST_B and emits HAP | Connect early_boot_prim_rst_b to a downstream device PRIM_RST_B input; subscribe to pwrgd_reset HAP | Call early_boot_prim_rst_b.signal_raise() then .signal_lower() | Downstream port sees asserted then deasserted; HAP callbacks recorded | Observe port transitions and HAP log entries |
| PMsync handshake signal behavior | Connect scu_start_pmsync_handshake to SCU's PMsync input; subscribe to HAP | Call scu_start_pmsync_handshake.signal_raise(); after test latency call signal_lower() | SCU port sees asserted then deasserted; HAP callbacks recorded | Observe port transitions and HAP log entries |
| Strap binding to register field | Configure strap_partition_id = N prior to instantiation | After instantiation, read sb_cr.POC_STRAPS.Pid and attribute.get() | Both return N | Compare register field and attribute.get() to configured value |

Implementation Notes (for Simics Device Model Developers)
--------------------------------------------------------
Key DML source files
- hwrs strap and attribute definitions: srv-pm/code/hwrs-gen2/hwrs-straps.dml. *Source: [srv-pm/code/hwrs-gen2/hwrs-straps.dml]*
- Resolved-IP register definitions: srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml (contains ip_disable_resolved_cr_reg template usage). *Source: [srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml]*
- Output-pin and HAP templates: srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml. *Source: [srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml]*
- Attribute templates and shared attributes: srv-pm/code/hwrs-gen2/attributes.dml. *Source: [srv-pm/code/hwrs-gen2/attributes.dml]*

Template dependencies and inheritance
- strap_attr_u64 / uint64_attr: attribute storage and get()/set() semantics for straps and fuse dwords. (Defined in attributes.dml)
- ip_disable_resolved_cr_reg: register template providing a read_register callback that synthesizes resolved value by OR-ing software and fuse registers. (Used in regs.dml)
- c_pin_out_hap / c_pin_out templates: provide signal_raise()/signal_lower() behaviors and HAP emission. Early-boot pins inherit these. (Defined in pwrgd-reset-templates.dml)

Extension / override points
- read_register callback: the ip_disable_resolved_cr_reg template implements the read-side behavior. To change resolution logic, override or replace the read_register callback in the DML definition.
- Add write handling: to accept writes or implement side-effects on writes, add write_register/after_write callbacks to the register DML.
- Hooks for timed sequencing: currently signal_raise()/signal_lower() are explicit calls. Introduce an FSM / timers if platform requires timed/automatic sequencing.
- Additional fuse/feature words: add attributes (uint64_attr) for extra sku_feature_dwordN and bind them into new resolved logic if needed.

Simulation fidelity / known differences
- Resolved register writes are ignored — the template presents the register as read-only (osdml_read_only) and discards writes. This models the hardware policy that fuse bits override but differs if hardware allows write-to-clear semantics. *Source: [srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml]*
- Straps and fuses are static attributes sampled at instantiation / power-on. The model does not simulate in-hardware one-time-programming events or asynchronous fuse blow timings.
- No internal FSM is present for more complex handshake behaviors; signal transitions occur only when model code explicitly calls signal_raise()/signal_lower().

Platform Integration Notes (for Platform Architects)
---------------------------------------------------
Role in the Simics platform
- Provides board and SKU provisioning information and early-boot control outputs required to sequence the platform during bring-up and to let firmware discover socket/partition identity and SKU/configuration features.

Required PORT/CONNECT connections and counterparts
- early_boot_prim_rst_b (CONNECT) -> connect to downstream PRIM_RST_B input(s) on power-management or SOC devices that expect an active-low early primary reset. The downstream side must accept active-low semantics. HAP consumers should subscribe to pwrgd_reset group for observation. *Source: [srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml]*
- scu_start_pmsync_handshake (CONNECT) -> connect to the System Control Unit (SCU) PMsync handshake input port. The SCU model should implement a corresponding input PORT to receive this signal and optionally generate replies if required by platform sequences. *Source: [srv-pm/code/hwrs-gen2/pwrgd-reset-templates.dml]*
- No inbound PORTs are required by this capability (it does not consume signal inputs).

Dependencies on other capabilities / platform services
- Firmware/device models that read sb_cr registers depend on strap and fuse attributes being configured correctly prior to or at instantiation.
- HAP subscription/monitoring is necessary for automated tests to observe signal transitions; test harnesses should set up HAP callbacks for pwrgd_reset and other groups used by c_pin_out_hap.
- Other Simics devices driven by early_boot_prim_rst_b and scu_start_pmsync_handshake must be present in the platform configuration and connected to these CONNECT nodes.

Configuration parameters that affect this capability
- strap attributes: board_id0..board_id4 (uint64_attr) — set at instantiation to model board identity. *Source: [srv-pm/code/hwrs-gen2/hwrs-straps.dml]*
- strap_socket_id (strap_attr_u64), strap_partition_id (strap_attr_u64) — used for socket/partition identity and bound to sb_cr.POC_STRAPS fields. *Source: [srv-pm/code/hwrs-gen2/hwrs-straps.dml]*
- sku_feature_dword0..sku_feature_dword9 and ip_disable_fuses_dword9 (uint64_attr) — configured fuse/SKU words consumed by resolved-IP computation. *Source: [srv-pm/code/hwrs-gen2/hwrs-straps.dml]*
- is_primary_imh and other role flags (where present) can modify whether the model drives certain outputs; consult attributes.dml for exact flag names. *Source: [srv-pm/code/hwrs-gen2/attributes.dml]*

Notes and references
- The register synthesis behavior and the strap attribute bindings are the authoritative model of how firmware will see OEM and fuse state in simulation. Tests and platform scripts should rely on attributes being set at instantiation for deterministic behavior. *Source: [srv-pm/bt/dmr-imh-b0-fv-devs/dmr-imh-hwrs-fv/dmr_imh_b0_hwrs_fv_regs.dml]*

If you need concrete DML snippets or example instantiation scripts that set strap/fuse attributes and subscribe to the HAPs, I can provide illustrative examples for test harnesses and device model extension points.