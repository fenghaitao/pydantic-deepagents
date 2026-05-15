# © 2026 Intel Corporation
#
# This software and the related documents are Intel copyrighted materials, and
# your use of them is governed by the express license under which they were
# provided to you ("License"). Unless the License provides otherwise, you may
# not use, modify, copy, publish, distribute, disclose or transmit this software
# or the related documents without Intel's prior written permission.
#
# This software and the related documents are provided as is, with no express or
# implied warranties, other than those that are expressly stated in the License.

import stest

# Create a sample transaction device
dut = SIM_create_object("sample_device_cxx_transaction", "dut", [])

# Test initial value is 0
stest.expect_equal(dut.value, 0)

# Test write via transaction
t = transaction_t(size = 4, write = True, value_le = 0x12345678)
result = dut.iface.transaction.issue(t, 0)
stest.expect_equal(result, simics.Sim_PE_No_Exception)
stest.expect_equal(dut.value, 0x12345678)

# Test read via transaction
t = transaction_t(size = 4, read = True)
result = dut.iface.transaction.issue(t, 0)
stest.expect_equal(result, simics.Sim_PE_No_Exception)
stest.expect_equal(t.value_le, 0x12345678)

# Test write another value
t = transaction_t(size = 4, write = True, value_le = 0xDEADBEEF)
result = dut.iface.transaction.issue(t, 0x1000)
stest.expect_equal(result, simics.Sim_PE_No_Exception)
stest.expect_equal(dut.value, 0xDEADBEEF)

# Test read the new value
t = transaction_t(size = 4, read = True)
result = dut.iface.transaction.issue(t, 0x1000)
stest.expect_equal(result, simics.Sim_PE_No_Exception)
stest.expect_equal(t.value_le, 0xDEADBEEF)

# Test attribute write
dut.value = 0xCAFEBABE
stest.expect_equal(dut.value, 0xCAFEBABE)

# Test read via transaction after attribute write
t = transaction_t(size = 4, read = True)
result = dut.iface.transaction.issue(t, 0x2000)
stest.expect_equal(result, simics.Sim_PE_No_Exception)
stest.expect_equal(t.value_le, 0xCAFEBABE)
