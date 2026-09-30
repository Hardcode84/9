# Systems source requirements for RMD

Date: 2026-09-30. Status: source study and design requirements.

Use direct embedded links as the primary list representation. Keep node storage
and ownership under application control. Automatic unlinking and stable addresses
remove common errors. They do not establish the lifetime of every saved pointer.

This study uses real callers in Linux, GCC, LLVM, and Coho. Three subagents
examined Linux, GCC, and LLVM separately. The Coho review follows the user's
linked example. The findings define required operations; they do not prove a
complete safe language or C-level compilation speed.
See the [language proposal](language-exploration.md#69-intrusive-lists-with-individual-destruction-and-reuse)
for the direct-link experiment and the [compiler profiles](compiler-profiles.md)
for the separate timing evidence.

## Source revisions

Use these fixed revisions to reproduce the inspection. These are selected
snapshots, not claims about the latest releases. Append each relative source
path below to its repository's commit URL.

| Project | Reference | Commit |
|---|---|---|
| Linux | v6.12 | [adc218676eef25575469234709c2d87185ca223a](https://github.com/torvalds/linux/tree/adc218676eef25575469234709c2d87185ca223a) |
| GCC | releases/gcc-13.3.0 | [b71f1de6e9cf7181a288c0f39f9b1ef6580cf5c8](https://github.com/gcc-mirror/gcc/tree/b71f1de6e9cf7181a288c0f39f9b1ef6580cf5c8) |
| LLVM | llvmorg-20.1.8 | [87f0227cb60147a26a1eeb4fb06e3b505e9c7261](https://github.com/llvm/llvm-project/tree/87f0227cb60147a26a1eeb4fb06e3b505e9c7261) |
| Coho | Linked repository, pinned during review | [c545721bac81f9bff567a29c337ce18c56766b32](https://github.com/webcoyote/coho/tree/c545721bac81f9bff567a29c337ce18c56766b32) |

## The direct list example

Patrick Wyatt's article describes intrusive hooks that remove themselves when
their object is destroyed. One object can have several hooks. The program owns
the object independently of its list memberships.
[Article](https://www.codeofhonor.com/blog/avoiding-game-crashes-related-to-linked-lists/)

In the pinned Coho header, a hook stores a next-object pointer and a previous-hook
pointer. The head stores a hook and a member offset. These imply 16 bytes per
hook and 24 bytes per head on an ordinary 64-bit ABI. No allocation occurs on
insertion. Hook destruction unlinks; head destruction detaches surviving nodes.
Payload deletion is separate. Copying is disabled. Detached hooks contain
self-references, so relocation also needs repair. The header uses a tagged
sentinel; its exact pointer arithmetic is not a language requirement.
[Fields and cleanup](https://github.com/webcoyote/coho/blob/c545721bac81f9bff567a29c337ce18c56766b32/Base/List.h#L111-L234),
[head and deletion](https://github.com/webcoyote/coho/blob/c545721bac81f9bff567a29c337ce18c56766b32/Base/List.h#L283-L359)

Design consequence: start from this small storage and ownership model.
Do not add an allocation registry or a list identity merely to detach a hook.
Define self-insertion before mutation. Keep synchronization and saved-pointer
lifetimes explicit. A raw-pointer precondition is not a proved safe-code rule.

Source defect: `InsertBefore(node, node)` detaches the hook, then uses that same
hook as its insertion anchor. Reciprocal links become inconsistent. A self-case
check before detach can make this operation a no-op.

## Linux callers

### Basic links and bulk transfer

Linux's circular list has two pointers per hook. Unlink does not destroy the
payload. The splice primitive changes four boundary links; the initializing
variant also resets the source head. This permits constant-time transfer between
nonempty lists. The safe iteration macro saves the successor before the body.
It does not protect that saved pointer from concurrent reclamation.
[Layout](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/include/linux/types.h#L193-L203),
[splice](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/include/linux/list.h#L523-L575),
[iteration](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/include/linux/list.h#L857-L868)

Design consequence: do not require a per-node membership ID that must change on
every splice. Prefer removal through the hook itself. Treat removal from a named
expected list as a separate API with its own validation cost.

### Stack waiters

In `do_wait_for_common`, a stack waiter remains linked while the caller releases
the completion lock and sleeps. The caller reacquires the lock and ensures that
the waiter is detached before return. Queue membership does not own this storage.
`swake_up_all` moves waiters to a temporary stack head and can release the queue
lock between wake operations.
[Completion wait](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/kernel/sched/completion.c#L80-L121),
[bulk wake](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/kernel/sched/swait.c#L41-L89)

Design consequence: permit scoped publication of caller-owned stable storage.
A local head does not imply exclusive ownership of its nodes. A mandatory
owning pool changes this allocation and access contract.

### Several hooks and different cleanup phases

An inode has separate writeback, LRU, superblock, and writeback-wait hooks.
`wait_sb_inodes` splices nodes to a stack head under the `s_inode_wblist_lock`
spinlock. Completion can still unlink those nodes. The waiting path releases
that lock while RCU still protects the inode. For an eligible inode, it acquires
an inode reference under `i_lock`, leaves RCU, then waits for IO.
[Inode fields](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/include/linux/fs.h#L692-L708),
[writeback wait](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/fs/fs-writeback.c#L2609-L2690)

The LRU path can pin an inode, release locks, reclaim data, and retry.
Freeable inodes move to a temporary list. That list is drained outside the LRU
walk. Eviction removes other memberships and waits for writeback. The fallback
release path defers allocator release through RCU. The LRU walker restarts after
a callback reports that it released the lock.
[Isolation and drain](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/fs/inode.c#L883-L964),
[eviction](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/fs/inode.c#L687-L777),
[deferred release](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/fs/inode.c#L244-L320),
[walk restart](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/mm/list_lru.c#L223-L261)

Design consequence: distinguish structural locks, lifetime pins, unlink,
destruction, and allocator reuse. A single exclusive loan over an owning pool
does not preserve these independent access scopes.

### RCU and field pointers

RCU permits readers to retain access while writers remove a node. A grace period
delays reuse until the relevant readers finish. `list_del_rcu` retains a forward
link that readers can still need. It does not permit immediate storage release.
[RCU deletion contract](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/include/linux/rculist.h#L132-L160)

The packet-handler registry provides a concrete caller. `__dev_remove_pack`
unlinks under its writer lock. `dev_remove_pack` also waits with
`synchronize_net`. Packet delivery traverses the registry and calls handlers.
The unlink operation alone does not complete this lifetime protocol.
[Remove operations](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/net/core/dev.c#L623-L662),
[delivery](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/net/core/dev.c#L2234-L2259)

Linux hash-list hooks store `next` and `pprev`. The latter points to the pointer
slot that refers to this node. PID membership uses an array of embedded hooks.
`find_get_task_by_vpid` acquires a task reference while under RCU, then returns
after leaving that read section.
[Hook layout](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/include/linux/types.h#L197-L203),
[PID attachment](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/kernel/pid.c#L340-L367),
[reference acquisition](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/kernel/pid.c#L437-L449)

Design consequence: support typed field addresses and stable embedded hooks.
A generation check supplies neither a lifetime pin nor memory ordering.
Atomics and reclamation remain explicit operations, with costs only where used.

## GCC callers

### Mutable traversal and scoped markers

`gsi_remove` removes statement membership without freeing the statement.
`gsi_set_stmt` preserves links so copied iterators can advance. Movement uses
detach and reinsert operations. `make_blocks` copies a saved iterator before a
move that changes the passed iterator.
[List operations](https://github.com/gcc-mirror/gcc/blob/b71f1de6e9cf7181a288c0f39f9b1ef6580cf5c8/gcc/gimple-iterator.cc#L369),
[caller](https://github.com/gcc-mirror/gcc/blob/b71f1de6e9cf7181a288c0f39f9b1ef6580cf5c8/gcc/tree-cfg.cc#L602)

An SSA use iterator embeds a stack marker. Mutable traversal inserts that marker
into a persistent use list; RAII removes it on scope exit. `remove_dead_phis`
changes use links during traversal.
[Iterator and cleanup](https://github.com/gcc-mirror/gcc/blob/b71f1de6e9cf7181a288c0f39f9b1ef6580cf5c8/gcc/ssa-iterators.h#L58-L103),
[marker insertion](https://github.com/gcc-mirror/gcc/blob/b71f1de6e9cf7181a288c0f39f9b1ef6580cf5c8/gcc/ssa-iterators.h#L929),
[DCE caller](https://github.com/gcc-mirror/gcc/blob/b71f1de6e9cf7181a288c0f39f9b1ef6580cf5c8/gcc/tree-ssa-dce.cc#L1018-L1047)

Design consequence: a ban on all stored borrowed addresses rejects this source
pattern. Test scoped attachment, stable local addresses, guaranteed detach,
and mutation through the iterator. Cleanup alone does not prevent alias escape.

### Relocation and operand identity

`resize_phi_node` copies a variable-size PHI to larger storage and repairs its
embedded use links. The caller repairs the defining-statement reference and
recycles the old node. Removing an argument can move the final argument into the
vacated slot. A live node identity plus operand index can then identify a
different logical operand.
[Growth and caller](https://github.com/gcc-mirror/gcc/blob/b71f1de6e9cf7181a288c0f39f9b1ef6580cf5c8/gcc/tree-phinodes.cc#L237-L304),
[argument removal](https://github.com/gcc-mirror/gcc/blob/b71f1de6e9cf7181a288c0f39f9b1ef6580cf5c8/gcc/tree-phinodes.cc#L388)

Design consequence: support explicit relocation with repair, or measure a
different representation. Define operand invalidation separately from node
destruction. Permanent pinning of every object is not a complete answer.

### Graph edits and reuse barriers

CFG edges occupy two adjacency vectors. Removing an edge repairs a swapped
edge's index. Hooks also remove the corresponding PHI argument.
SSA-name reuse has another condition: GCC clears the scalar-evolution cache
before moving released names to its available free list.
[CFG edits](https://github.com/gcc-mirror/gcc/blob/b71f1de6e9cf7181a288c0f39f9b1ef6580cf5c8/gcc/cfg.cc#L263),
[PHI hooks](https://github.com/gcc-mirror/gcc/blob/b71f1de6e9cf7181a288c0f39f9b1ef6580cf5c8/gcc/tree-cfg.cc#L9112),
[reuse barrier](https://github.com/gcc-mirror/gcc/blob/b71f1de6e9cf7181a288c0f39f9b1ef6580cf5c8/gcc/tree-ssanames.cc#L324)

Design consequence: one edit can affect several nodes, operands, and analysis
tables. Memory identity checks do not establish these semantic invariants.
Keep allocation policy explicit; GCC's selected collector does not imply a
required language collector.

## LLVM callers

### Ownership transfer and immediate erasure

`ReplaceInstWithInst` inserts a detached replacement, replaces the old uses,
erases the old instruction, and keeps the replacement iterator.
Block merging retains instruction pointers across splice and analysis updates.
The transfer callbacks update each moved instruction's parent and, when needed,
its symbol table. Such an LLVM range transfer can require per-node work even
though the underlying link splice is constant-time.
[Replacement](https://github.com/llvm/llvm-project/blob/87f0227cb60147a26a1eeb4fb06e3b505e9c7261/llvm/lib/Transforms/Utils/BasicBlockUtils.cpp#L710-L740),
[merge](https://github.com/llvm/llvm-project/blob/87f0227cb60147a26a1eeb4fb06e3b505e9c7261/llvm/lib/Transforms/Utils/BasicBlockUtils.cpp#L275-L307),
[transfer callbacks](https://github.com/llvm/llvm-project/blob/87f0227cb60147a26a1eeb4fb06e3b505e9c7261/llvm/lib/IR/SymbolTableListTraitsImpl.h#L66-L119)

Design consequence: support both non-owning and owning intrusive containers.
Keep detach, erase, and transfer distinct. Stable node identity must survive
membership changes where callers retain it.

### Use edges and separate operand storage

Each `Use` belongs to an operand and appears in the referenced value's use list.
This revision stores four pointers: `Val`, `Next`, `Prev`, and `Parent`.
The old header comment about recovering the parent from tagged bits does not
describe these fields. Growing a separate operand array destroys the old uses
while preserving the user object's address. PHI removal can also shift operands.
[Use fields](https://github.com/llvm/llvm-project/blob/87f0227cb60147a26a1eeb4fb06e3b505e9c7261/llvm/include/llvm/IR/Use.h#L39-L102),
[operand growth](https://github.com/llvm/llvm-project/blob/87f0227cb60147a26a1eeb4fb06e3b505e9c7261/llvm/lib/IR/User.cpp#L50-L89),
[PHI removal](https://github.com/llvm/llvm-project/blob/87f0227cb60147a26a1eeb4fb06e3b505e9c7261/llvm/lib/IR/Instructions.cpp#L137-L158)

Design consequence: a whole-node lifetime rule does not establish operand
identity. Test pointers to embedded fields and variable operand storage.

### Cycles and mutation callbacks

Function-body teardown clears outgoing references before deleting blocks.
Replacement of all uses, called RAUW, has a different protocol. Observer
callbacks run before ordinary uses change. Observers can change their own
registration during notification.
[Teardown](https://github.com/llvm/llvm-project/blob/87f0227cb60147a26a1eeb4fb06e3b505e9c7261/llvm/lib/IR/Function.cpp#L607-L616),
[replacement order](https://github.com/llvm/llvm-project/blob/87f0227cb60147a26a1eeb4fb06e3b505e9c7261/llvm/lib/IR/Value.cpp#L503-L535),
[observer loop](https://github.com/llvm/llvm-project/blob/87f0227cb60147a26a1eeb4fb06e3b505e9c7261/llvm/lib/IR/Value.cpp#L1255-L1289)

Design consequence: RAII cannot infer every graph destruction order.
Define callback phases and invalidation. A universal ban on callbacks during
graph edits cannot reproduce this API.

### Layout and allocation control

LLVM uses context-owned type identities, prefix operand storage, and separate
variable operand allocations. Pointer tagging is used in list and value-handle
machinery. Instruction hooks also carry a parent pointer.
[Type allocation](https://github.com/llvm/llvm-project/blob/87f0227cb60147a26a1eeb4fb06e3b505e9c7261/llvm/lib/IR/Type.cpp#L311-L384),
[operand allocation](https://github.com/llvm/llvm-project/blob/87f0227cb60147a26a1eeb4fb06e3b505e9c7261/llvm/lib/IR/User.cpp#L133-L160),
[list storage](https://github.com/llvm/llvm-project/blob/87f0227cb60147a26a1eeb4fb06e3b505e9c7261/llvm/include/llvm/ADT/ilist_node_base.h#L20-L56),
[value handles](https://github.com/llvm/llvm-project/blob/87f0227cb60147a26a1eeb4fb06e3b505e9c7261/llvm/include/llvm/IR/ValueHandle.h#L29-L51)

Design consequence: retain alignment, typed field projection, variable-size
storage, explicit allocators, and an escape hatch for raw layout operations.
A type context's lifetime does not force all instructions into the same arena.

## Consequences for the language

These are design conclusions from the inspected code.

| Area | Required direction |
|---|---|
| Storage | Permit ordinary addresses and application-selected allocation. No mandatory pool or global object registry. |
| Ownership | Distinguish ownership, membership, observation, and temporary access. |
| Cleanup | Support deterministic cleanup and explicit retirement before storage reuse. |
| Movement | Prevent accidental movement of initialized address-dependent objects; permit explicit repair operations. |
| Aliasing | Do not interpret every mutable address as a unique borrow. Define the permission for each access category. |
| Concurrency | Keep locks, atomics, reader lifetime, and reclamation protocols explicit. |
| Abstraction | Provide reusable typed operations; do not require C++ overload search or arbitrary compile-time execution. |
| Frontend | Summarize contracts in signatures and type layouts. Check independent bodies in parallel. |

A declared address-stability rule and automatic cleanup do not inherently need a
global heap solver. This is a design observation, not a timing result.
A safe persistent-pointer contract can require more work. Measure that work
inside the full frontend boundary. Do not move it to a linker or runtime service
and omit its cost.

The present research has not proved a small safe direct-pointer model with
individual reclamation. The exact missing contract must cover stored aliases,
subobject validity, and cleanup that changes other nodes. A plain pointer plus
RAII is a useful baseline, but cannot be called fully memory safe. An optional
checked pointer need not dictate allocation; it must still expose its metadata,
assignment, access, and destruction costs.

## Acceptance experiments

Freeze small source-derived cases before adding more language machinery.
These are proposed tests. No RMD compiler or translation of these cases exists.

| Case | Required visible result and failure tests |
|---|---|
| Coho-style two-hook node | Traverse both lists after transfer, individual destruction, and exact-address reuse. Destroy head and nodes in either order. Define self-insertion and saved-cursor behavior. |
| Linux stack waiter | Wake, timeout, cancel, and return without a heap wrapper or surviving stack address. Exercise cleanup while another actor can remove the hook. |
| Linux bulk splice and reclamation | Count bounded boundary writes for nonempty lists. Pin an object across lock release; detach under a lock. Complete the reader-lifetime protocol before destroying reader-visible state or reusing storage. |
| GCC SSA edit | Change uses during traversal, exit early, grow a PHI, remove a middle edge, repair operands, and reuse storage after cache invalidation. Print and verify the resulting IR. |
| LLVM replacement | Insert, replace uses, transfer nodes, grow operands, and erase. Include self-removing observers and cyclic teardown. Verify and print the final IR. |

For each case, preserve the source algorithm's storage and synchronization
requirements. Count bytes, allocations, touched nodes, checks, and retained
storage. Compare direct C/C++ and any equivalent checked baseline.
Measure one-worker check and backend-handoff time before parallel speedup.
Use the pass rules in the [language proposal](language-exploration.md#10-production-witness-and-acceptance-gates).

Stop a candidate when it cannot express its case without a hidden unsafe
operation, an imposed allocation model, excessive annotations, or a failed
C-speed gate. The next step is then a specific change to that access contract
and the same test. A successful two-node example does not authorize a general
graph framework.
