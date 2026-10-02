/* SPDX-License-Identifier: Apache-2.0 */

#include <stdio.h>
#include <sys/prctl.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    if (argc < 2) {
        fputs("usage: thp-off COMMAND ARGUMENT...\n", stderr);
        return 2;
    }
    if (prctl(PR_SET_THP_DISABLE, 1UL, 0UL, 0UL, 0UL) != 0 ||
        prctl(PR_GET_THP_DISABLE, 0UL, 0UL, 0UL, 0UL) != 1) {
        fputs("cannot disable transparent huge pages\n", stderr);
        return 1;
    }
    execvp(argv[1], argv + 1);
    perror("execvp");
    return 127;
}
