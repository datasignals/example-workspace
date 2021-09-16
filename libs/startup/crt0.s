// This is a startup code for the tutorial codasip_urisc processor.
// The main task of the startup code for C language programs
// is to initialize the stack pointer and call the main function.
//
// Also bodies of functions used in tests abort and exit are present here.
//

    // The section .crt0 is always put at address 0.
    // This can be changed by modifying the GNU linker script.
    .section .crt0, "ax"

    // Symbol start is used to obtain entry point information.
_start:
    .global _start

    // When the C compiler is generated, information about the
    // used ABI (Application Binary Interface) is printed.
    // ABI, among other things, defines which register is used as a stack
    // pointer. To the stack pointer we put initial stack pointer address
    // using a combination of movsi and movhi instructions.
    r0 = movsi _stack & 0xffff
    r0 = movhi _stack >> 16 & 0xffff

    // Overwrite return exit code
    // Must not be used for functions that use argv and argc main arguments!
    r4 = movsi 1

    // Now we can call the main function.
    call main

    // Once the program returns from main, the simulation can be stopped,
    // or the processor can be halted.
    // At the end the register for first integer return value
    // contains the application's exit code.
    halt
    nop
    nop
    nop


abort:
    .global abort
    .equiv abort_exit_code, 134

    // We put exit code value to the register for first integer return value.
    nop
    nop
    nop
    r4 = movsi abort_exit_code
    nop
    nop
    nop
    halt
    nop
    nop
    nop

exit:
    .global exit
    // For codasip_urisc, the register for first integer function argument is the same as
    // the register for first integer return value (R4), therefore we can keep
    // the exit code value in R4.
    nop
    nop
    nop
    halt
    nop
    nop
    nop


    // Auxiliary section to handle taken jumps/returns that could have
    // issued invalid instructions from data sections into the instruction decoder
    .section .text_jump_padding, "ax"
    .word 0
    .word 0
    .word 0

