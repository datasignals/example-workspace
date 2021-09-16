    .text

// r4 - 1st argument and return value
setjmp:
    .global setjmp
    st r0, [r4 + 0]
    st r1, [r4 + 4]
    st r2, [r4 + 8]
    st r3, [r4 + 12]
    st r4, [r4 + 16]
    st r5, [r4 + 20]
    st r6, [r4 + 24]
    st r7, [r4 + 28]
    st r8, [r4 + 32]
    st r9, [r4 + 36]
    st r10, [r4 + 40]
    st r11, [r4 + 44]
    st r12, [r4 + 48]
    st r13, [r4 + 52]
    st r14, [r4 + 56]
    st r15, [r4 + 60]
    st r16, [r4 + 64]
    st r17, [r4 + 68]
    st r18, [r4 + 72]
    st r19, [r4 + 76]
    st r20, [r4 + 80]
    st r21, [r4 + 84]
    st r22, [r4 + 88]
    st r23, [r4 + 92]
    st r24, [r4 + 96]
    st r25, [r4 + 100]
    st r26, [r4 + 104]
    st r27, [r4 + 108]
    st r28, [r4 + 112]
    st r29, [r4 + 116]
    st r30, [r4 + 120]
    st r31, [r4 + 124]

    // Return 0 to caller
    r4 = movsi 0

    jumpr r3

// r4 - first argument and return value
// r5 - second argument
longjmp:
   .global longjmp
   r31 = ld [r4 + 124]
   r30 = ld [r4 + 120]
   r29 = ld [r4 + 116]
   r28 = ld [r4 + 112]
   r27 = ld [r4 + 108]
   r26 = ld [r4 + 104]
   r25 = ld [r4 + 100]
   r24 = ld [r4 + 96]
   r23 = ld [r4 + 92]
   r22 = ld [r4 + 88]
   r21 = ld [r4 + 84]
   r20 = ld [r4 + 80]
   r19 = ld [r4 + 76]
   r18 = ld [r4 + 72]
   r17 = ld [r4 + 68]
   r16 = ld [r4 + 64]
   r15 = ld [r4 + 60]
   r14 = ld [r4 + 56]
   r13 = ld [r4 + 52]
   r12 = ld [r4 + 48]
   r11 = ld [r4 + 44]
   r10 = ld [r4 + 40]
   r9 = ld [r4 + 36]
   r8 = ld [r4 + 32]
   r7 = ld [r4 + 28]
   r6 = ld [r4 + 24]
   r3 = ld [r4 + 12]
   r2 = ld [r4 + 8]
   r1 = ld [r4 + 4]
   r0 = ld [r4 + 0]

   // swap r4 and r5
   r4 = xor r4, r5
   r5 = xor r5, r4
   r4 = xor r4, r5

   r5 = ld [r5 + 20]

   // if longjmp() was to return 0, return 1 instead
   jumpnz r4, lab_1
   r4 = movsi 1
lab_1:

   jumpr r3

