// SPDX-License-Identifier: Apache-2.0

use std::cell::UnsafeCell;
use std::marker::PhantomPinned;
use std::pin::Pin;
use std::ptr;

struct Node {
    prev: [*mut Node; 2],
    next: [*mut Node; 2],
    value: i64,
}
pub struct Owner {
    node: *mut Node,
}
pub struct Head {
    node: UnsafeCell<Node>,
    _pin: PhantomPinned,
}
pub struct Cursor {
    node: *mut Node,
}

fn empty(value: i64) -> Node {
    Node {
        prev: [ptr::null_mut(); 2],
        next: [ptr::null_mut(); 2],
        value,
    }
}

// All pointers name live nodes. Only the selected membership is changed.
unsafe fn unlink(node: *mut Node, hook: usize) {
    unsafe {
        let before = (*node).prev[hook];
        let after = (*node).next[hook];
        (*before).next[hook] = after;
        (*after).prev[hook] = before;
        (*node).prev[hook] = node;
        (*node).next[hook] = node;
    }
}

fn head_node(head: Pin<&Head>, hook: usize) -> *mut Node {
    let node = head.node.get();
    // Pin holds the stack address. Null links mark an unused membership.
    unsafe {
        if (*node).next[hook].is_null() {
            (*node).prev[hook] = node;
            (*node).next[hook] = node;
        }
    }
    node
}

impl Head {
    pub fn new() -> Self {
        Head {
            node: UnsafeCell::new(empty(0)),
            _pin: PhantomPinned,
        }
    }
}

impl Drop for Head {
    fn drop(&mut self) {
        let node = self.node.get();
        // A head can also be dropped before it was pinned and initialized.
        unsafe {
            for hook in 0..2 {
                if !(*node).next[hook].is_null() {
                    while (*node).next[hook] != node {
                        unlink((*node).next[hook], hook);
                    }
                }
            }
        }
    }
}

pub fn owner_new(value: i64) -> Owner {
    let node = Box::into_raw(Box::new(empty(value)));
    // No references escape before self-links are set.
    unsafe {
        (*node).prev = [node; 2];
        (*node).next = [node; 2];
    }
    Owner { node }
}

impl Drop for Owner {
    fn drop(&mut self) {
        // Retirement detaches both hooks before the allocation is released.
        unsafe {
            unlink(self.node, 0);
            unlink(self.node, 1);
            drop(Box::from_raw(self.node));
        }
    }
}

fn insert(head: Pin<&Head>, owner: &Owner, hook: usize) {
    let at = head_node(head, hook);
    let node = owner.node;
    // Owners keep heap addresses. Pinned heads and owner retirement repair links.
    unsafe {
        unlink(node, hook);
        let after = (*at).next[hook];
        (*node).prev[hook] = at;
        (*node).next[hook] = after;
        (*after).prev[hook] = node;
        (*at).next[hook] = node;
    }
}

fn count(head: Pin<&Head>, hook: usize) -> usize {
    let node = head_node(head, hook);
    let mut count = 0;
    // The list is repaired before any node or head can be released.
    unsafe {
        let mut cursor = (*node).next[hook];
        while cursor != node {
            count += 1;
            cursor = (*cursor).next[hook];
        }
    }
    count
}

pub fn ready_init(head: Pin<&Head>) {
    head_node(head, 0);
}
pub fn active_init(head: Pin<&Head>) {
    head_node(head, 1);
}
pub fn ready_insert(head: Pin<&Head>, owner: &Owner) {
    insert(head, owner, 0);
}
pub fn active_insert(head: Pin<&Head>, owner: &Owner) {
    insert(head, owner, 1);
}
pub fn ready_count(head: Pin<&Head>) -> usize {
    count(head, 0)
}
pub fn active_count(head: Pin<&Head>) -> usize {
    count(head, 1)
}
pub fn ready_first(head: Pin<&Head>) -> Cursor {
    let node = head_node(head, 0);
    // A cursor can hold this address; using it requires a separate lifetime proof.
    Cursor {
        node: unsafe { (*node).next[0] },
    }
}
pub fn ready_end(head: Pin<&Head>) -> Cursor {
    Cursor {
        node: head_node(head, 0),
    }
}
pub fn cursor_equal(a: &Cursor, b: &Cursor) -> bool {
    a.node == b.node
}
pub fn owner_value(owner: &Owner) -> &i64 {
    // Safe operations change hooks only. The owner borrow prevents retirement.
    unsafe { &(*owner.node).value }
}

/// The node must stay live and its payload must stay unchanged during the result loan.
pub unsafe fn cursor_value(cursor: &Cursor) -> &i64 {
    unsafe { &(*cursor.node).value }
}
/// The node must stay live; all other payload access is excluded during the result loan.
pub unsafe fn cursor_mut(cursor: &mut Cursor) -> &mut i64 {
    unsafe { &mut (*cursor.node).value }
}
/// The current node and its next link must remain valid for this call.
pub unsafe fn cursor_advance(cursor: &mut Cursor) {
    unsafe {
        cursor.node = (*cursor.node).next[0];
    }
}
