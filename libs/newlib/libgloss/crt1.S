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

    // run global constructors
    jump ctors_init

ctors_initialized:

    r4 = movsi _codasip_argc_address & 0xffff
    r4 = movhi _codasip_argc_address >> 16 & 0xffff

    r4 = ld [ r4 + 0 ]

    r5 = movsi _codasip_argv_pointers & 0xffff
    r5 = movhi _codasip_argv_pointers >> 16 & 0xffff

    // Now we can call the main function.
    call main
    call exit

    // Once the program returns from main, the simulation can be stopped,
    // or the processor can be halted.
    // At the end the register for first integer return value
    // contains the application's exit code.
    halt
    nop
    nop
    nop

ctors_init:
    // the following symbols are provided by linker
    r6 = movsi __CTOR_LIST__ & 0xffff
    r6 = movhi __CTOR_LIST__ >> 16 & 0xffff

    // reserve space on stack (8 bytes to keep stack aligned)
    r0 = addi r0, -8

ctors_loop:
    // r7 is restored each call
    r7 = movsi __CTOR_END__ & 0xffff
    r7 = movhi __CTOR_END__ >> 16 & 0xffff

    r8 = eq r6, r7 // r6 is loop counter
    jumpnz r8, ctors_end

    // store r6 to stack because it can be overwritten
    st r6, [ r0 + 0 ]

    // load called function address
    r6 = ld [ r6 + 0 ]
    nop
    callr r6

    // restore r6
    r6 = ld [ r0 + 0 ]
    nop

    r6 = addi r6, 4 // next initializer
    jump ctors_loop
ctors_end:
    r6 = movsi 0
    r7 = movsi 0

    // move stack pointer back
    r0 = addi r0, +8

    // and call main
    jump ctors_initialized

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

_exit:
    .global _exit
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

    // the following section holds program arguments
    // maximal count of arguments is 32
    // strings in arguments may have up to 512 bytes
    .section .progargs, "aw"
    .align 4
_codasip_argc_address:
    .global _codasip_argc_address
    .word 0 // contains argv value
_codasip_argv_pointers: // this address represents argv pointer value
    .global _codasip_argv_pointers
    .fill 32, 4, 0  // each word contains a pointer to the _codasip_argv_strings field, last pointer has value NULL
_codasip_argv_strings: // this field contains zero-terminated argv[x] strings
    .global _codasip_argv_strings
    .fill 512, 1, 0



    // auxiliary section to handle taken jumps/returns that could have
    // issued invalid instructions from data sections into the instruction decoder
    .section .text_jump_padding, "ax"
    .word 0
    .word 0
    .word 0


    // needed for C++, see http://wiki.osdev.org/C%2B%2B
    .section .data
    .global __dso_handle
    .weak   __dso_handle
__dso_handle:
    .long    0

