# Custom reader and assembly operation

Run from the repository root after `make all`:

```sh
build/rmd0 -o build/stage.s api/rmd0.rmd api/rmd0_host.rmd api/rmd0_x64.rmd examples/custom-stage/stage.rmd
gcc -no-pie build/stage.s build/librmd0.a build/librmd0_host.a -o build/stage
build/stage examples/custom-stage/answer.txt build/answer.s
gcc -no-pie build/answer.s examples/custom-stage/answer_main.c -o build/answer
build/answer
```

The last command returns status 42. It prints no text.

[stage.rmd](stage.rmd) is a compiler program built by `rmd0`. Its reader accepts
a decimal exit status from 0 through 255 and an optional final line feed.
The supplied [answer.txt](answer.txt) contains `42`.

The reader constructs an ordinary RMD syntax tree. The program checks that
tree, replaces the assembly operation for addition by zero, and emits an
`rmd_stage_answer` function. [answer_main.c](answer_main.c) calls that function.
The emitted assembly contains `# stage: add zero` from the selected operation.

See [reader-switch](../reader-switch/README.md) for a reader installed by a root
program while that same file is being executed.
