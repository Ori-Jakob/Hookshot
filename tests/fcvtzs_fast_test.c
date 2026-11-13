/* recomp_fp_to_int's FCVTZS fast path against the exact body: tests/test_fcvtzs_fast.py.

   fcvtzs_fast.h holds suyu's fixed-point helpers twice: fast_* as the runtime header has them, ref_* with
   RECOMP_NO_NATIVE_FP (the exact body only). Every case compares the value and the FPSR, through the inlined
   (constant width) form lifted code gets and through one with the widths unknown.

     fcvtzs_fast_test random N SEED | edges | all32 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fcvtzs_fast.h"

#define FZ (UINT64_C(1) << 24)

static long long checks, bad;

static uint64_t rng;
static uint64_t next(void) {
    rng ^= rng << 13;
    rng ^= rng >> 7;
    rng ^= rng << 17;
    return rng;
}

__attribute__((noinline)) static uint64_t fast_any(uint64_t b, unsigned fb, unsigned ib, uint64_t fpcr, uint64_t *s) {
    return fast_fp_to_int(b, fb, ib, 1, 3, fpcr, s);
}

static void check(uint64_t b, unsigned fb, unsigned ib, uint64_t fpcr, uint64_t fpsr) {
    uint64_t s_ref = fpsr, s_fast = fpsr, s_any = fpsr, r_ref, r_fast;
    if (fb == 32) b &= 0xffffffffu;
    if (fb == 32 && ib == 32) {
        r_ref = ref_fp_to_int(b, 32, 32, 1, 3, fpcr, &s_ref);
        r_fast = fast_fp_to_int(b, 32, 32, 1, 3, fpcr, &s_fast);
    } else if (fb == 32) {
        r_ref = ref_fp_to_int(b, 32, 64, 1, 3, fpcr, &s_ref);
        r_fast = fast_fp_to_int(b, 32, 64, 1, 3, fpcr, &s_fast);
    } else if (ib == 32) {
        r_ref = ref_fp_to_int(b, 64, 32, 1, 3, fpcr, &s_ref);
        r_fast = fast_fp_to_int(b, 64, 32, 1, 3, fpcr, &s_fast);
    } else {
        r_ref = ref_fp_to_int(b, 64, 64, 1, 3, fpcr, &s_ref);
        r_fast = fast_fp_to_int(b, 64, 64, 1, 3, fpcr, &s_fast);
    }
    const uint64_t r_any = fast_any(b, fb, ib, fpcr, &s_any);
    checks++;
    if (r_fast != r_ref || s_fast != s_ref || r_any != r_ref || s_any != s_ref) {
        if (bad < 10)
            printf("MISMATCH f%u->i%u bits=%llx fpcr=%llx fpsr=%llx: exact %llx/%llx, fast %llx/%llx, any %llx/%llx\n",
                   fb, ib, (unsigned long long)b, (unsigned long long)fpcr, (unsigned long long)fpsr,
                   (unsigned long long)r_ref, (unsigned long long)s_ref, (unsigned long long)r_fast,
                   (unsigned long long)s_fast, (unsigned long long)r_any, (unsigned long long)s_any);
        bad++;
    }
}

static uint64_t make(unsigned fb, uint64_t sign, uint64_t exponent, uint64_t mantissa) {
    return fb == 32 ? sign << 31 | (exponent & 255) << 23 | (mantissa & 0x7fffff)
                    : sign << 63 | (exponent & 2047) << 52 | (mantissa & UINT64_C(0xfffffffffffff));
}

/* Mostly exponents around the fast path's edges (|x| near 1 and near 2^(int_bits-1)), then any bits, zeros,
   subnormals, infinities and NaNs, under FZ on and off with other FPCR bits and any sticky FPSR. */
static void random_cases(long n) {
    for (long i = 0; i < n; i++) {
        const uint64_t r = next(), m = next();
        const unsigned fb = r & 1 ? 64 : 32, ib = r & 2 ? 64 : 32;
        const unsigned bias = fb == 32 ? 127 : 1023, emax = fb == 32 ? 255 : 2047;
        const uint64_t sign = (r >> 2) & 1;
        uint64_t b;
        switch ((r >> 3) & 15) {
        case 0: case 1: case 2: b = m; break;
        case 3: b = make(fb, sign, 0, m); break;
        case 4: b = make(fb, sign, emax, m >> ((r >> 7) & 63)); break;
        case 5: b = make(fb, sign, (r >> 7) & 1 ? emax : 0, (r >> 8) & 1); break;
        case 6: b = make(fb, sign, bias + ib - 1 - ((r >> 7) & 3), (r >> 9) & 1 ? m : 0); break;
        case 7: b = make(fb, sign, bias + ib - 2, (r >> 9) & 1 ? ~UINT64_C(0) : m); break;
        default: b = make(fb, sign, bias - 3 + (r >> 7) % (ib + 6), m); break;
        }
        uint64_t fpcr = (r >> 20) & 1 ? FZ : 0;
        if (((r >> 21) & 3) == 0) fpcr |= m & UINT64_C(0x07ffff1f);
        uint64_t fpsr = (r >> 23) & 1 ? (r >> 24) & 0x9f : 0;
        check(b, fb, ib, fpcr, fpsr);
    }
}

/* Every exponent, with the extreme and some middle mantissas. */
static void edges(void) {
    static const uint64_t fpcrs[] = {0, FZ, UINT64_C(3) << 22, FZ | UINT64_C(1) << 25};
    static const uint64_t fpsrs[] = {0, 16, 0x9f};
    for (unsigned fb = 32; fb <= 64; fb += 32) {
        const unsigned emax = fb == 32 ? 255 : 2047;
        const uint64_t mmax = fb == 32 ? 0x7fffff : UINT64_C(0xfffffffffffff);
        const uint64_t ms[] = {0, 1, 2, 3, mmax, mmax - 1, mmax >> 1, (mmax >> 1) + 1, mmax / 3, mmax / 7 * 5};
        for (unsigned ib = 32; ib <= 64; ib += 32)
            for (uint64_t e = 0; e <= emax; e++)
                for (unsigned k = 0; k < sizeof ms / sizeof *ms; k++)
                    for (uint64_t sign = 0; sign < 2; sign++)
                        for (unsigned c = 0; c < 4; c++)
                            for (unsigned s = 0; s < 3; s++) check(make(fb, sign, e, ms[k]), fb, ib, fpcrs[c], fpsrs[s]);
    }
}

/* Every binary32 input, to W and X, FZ off and on. */
static void all32(void) {
    for (unsigned ib = 32; ib <= 64; ib += 32)
        for (unsigned c = 0; c < 2; c++) {
            uint32_t b = 0;
            do check(b, 32, ib, c ? FZ : 0, 0);
            while (++b);
        }
}

int main(int argc, char **argv) {
#if defined(NEED_V3) && (defined(__x86_64__) || defined(_M_X64))
    __builtin_cpu_init();
    if (!__builtin_cpu_supports("avx2") || !__builtin_cpu_supports("fma") || !__builtin_cpu_supports("bmi2")) {
        printf("fcvtzs fast: not an x86-64-v3 CPU\n");
        return 3;
    }
#endif
    if (argc == 4 && !strcmp(argv[1], "random")) {
        rng = strtoull(argv[3], NULL, 10) | 1;
        random_cases(strtol(argv[2], NULL, 10));
    } else if (argc == 2 && !strcmp(argv[1], "edges")) {
        edges();
    } else if (argc == 2 && !strcmp(argv[1], "all32")) {
        all32();
    } else {
        printf("usage: fcvtzs_fast_test random N SEED | edges | all32\n");
        return 2;
    }
    printf("fcvtzs fast %s: %lld checks, %lld mismatches\n", argv[1], checks, bad);
    return bad != 0;
}
