// -*- mode: C++; c-file-style: "virtutech-c++" -*-

/*
  © 2026 Intel Corporation

  This software and the related documents are Intel copyrighted materials, and
  your use of them is governed by the express license under which they were
  provided to you ("License"). Unless the License provides otherwise, you may
  not use, modify, copy, publish, distribute, disclose or transmit this software
  or the related documents without Intel's prior written permission.

  This software and the related documents are provided as is, with no express or
  implied warranties, other than those that are expressly stated in the License.
*/

#include <simics/cc-api.h>
#include <simics/c++/model-iface/transaction.h>

/// Sample memory-mapped device demonstrating the transaction interface.
///
/// This sample shows how to implement the transaction interface for a
/// memory-mapped device in C++. The device provides a simple 32-bit register
/// that can be read and written via memory transactions.
///
/// The TransactionInterface is suitable for simple devices with a small number
/// of registers. You implement the issue() method directly and handle all read/
/// write transactions in a single place. This approach is appropriate when you
/// need low-level control over transaction handling and the register map is
/// straightforward.
///
/// For complex devices with many registers, banks, and fields, it is
/// recommended to use the C++ modeling API instead. Include simics/cc-modeling-
/// api.h and use the BankPort, Register, and Field classes to define your
/// device hierarchy. See sample-bank-by-code.cc for an example of this
/// approach.
class SampleTransaction : public simics::ConfObject,
                          public simics::iface::TransactionInterface {
  public:
    using ConfObject::ConfObject;

    static void init_class(simics::ConfClass *cls);

    // TransactionInterface
    exception_type_t issue(transaction_t *t, uint64 addr) override;

    uint32_t value {0};
};

void SampleTransaction::init_class(simics::ConfClass *cls) {
    cls->add(simics::Attribute("value", "i",
                               "The device value register",
                               ATTR_CLS_VAR(SampleTransaction, value)));

    // Register the transaction interface
    cls->add(simics::iface::TransactionInterface::Info());
}

exception_type_t SampleTransaction::issue(transaction_t *t, uint64 addr) {
    if (SIM_transaction_is_read(t)) {
        SIM_set_transaction_value_le(t, value);
        SIM_LOG_INFO(1, obj(), 0, "read from offset %lld: 0x%x", addr,
                     value);
    } else {
        value = SIM_get_transaction_value_le(t);
        SIM_LOG_INFO(1, obj(), 0, "write to offset %lld: 0x%x", addr,
                     value);
    }
    return Sim_PE_No_Exception;
}

static simics::RegisterClassWithSimics<SampleTransaction>
// coverity[global_init_order]
init_sample_transaction {
    "sample_device_cxx_transaction",
    "sample C++ transaction device",
    "Sample C++ device demonstrating the transaction interface"
};
