// SPDX-License-Identifier: Apache-2.0

use std::marker::PhantomData;
use std::ptr;

struct Branch {
    parent: *mut Branch,
    left: *mut Branch,
    right: *mut Branch,
    value: i64,
}

pub struct Tree {
    node: *mut Branch,
}

pub struct TreeCursor<'a> {
    node: *const Branch,
    origin: PhantomData<&'a Tree>,
}

pub fn tree_new(value: i64) -> Tree {
    let node = Box::into_raw(Box::new(Branch {
        parent: ptr::null_mut(),
        left: ptr::null_mut(),
        right: ptr::null_mut(),
        value,
    }));
    // The new allocation is owned here and has no borrowers.
    unsafe {
        (*node).parent = node;
    }
    Tree { node }
}

impl Drop for Tree {
    fn drop(&mut self) {
        let root = self.node;
        let mut cursor = root;
        // Each detached child is visited once. The parent survives its children.
        unsafe {
            while !cursor.is_null() {
                if !(*cursor).left.is_null() {
                    let child = (*cursor).left;
                    (*cursor).left = ptr::null_mut();
                    cursor = child;
                } else if !(*cursor).right.is_null() {
                    let child = (*cursor).right;
                    (*cursor).right = ptr::null_mut();
                    cursor = child;
                } else {
                    let parent = if cursor == root {
                        ptr::null_mut()
                    } else {
                        (*cursor).parent
                    };
                    drop(Box::from_raw(cursor));
                    cursor = parent;
                }
            }
        }
    }
}

pub fn tree_attach_left(parent: &mut Tree, child: Tree) {
    // Exclusive access excludes cursors. The consumed child has one owner.
    unsafe {
        assert!((*parent.node).left.is_null());
        (*parent.node).left = child.node;
        (*child.node).parent = parent.node;
    }
    std::mem::forget(child);
}

pub fn tree_take_left(parent: &mut Tree) -> Tree {
    // No cursor can survive this exclusive access. Reset the detached root.
    unsafe {
        let node = (*parent.node).left;
        assert!(!node.is_null());
        (*parent.node).left = ptr::null_mut();
        (*node).parent = node;
        Tree { node }
    }
}

pub fn tree_left(parent: &Tree) -> TreeCursor<'_> {
    // The cursor retains the whole owning tree, including the root fallback.
    let node = unsafe { (*parent.node).left };
    TreeCursor {
        node: if node.is_null() { parent.node } else { node },
        origin: PhantomData,
    }
}

pub fn tree_parent<'a>(cursor: &TreeCursor<'a>) -> TreeCursor<'a> {
    // Attachment and retirement require exclusive access to the retained tree.
    TreeCursor {
        node: unsafe { (*cursor.node).parent },
        origin: PhantomData,
    }
}

pub fn tree_value<'a>(cursor: &TreeCursor<'a>) -> &'a i64 {
    // The originating tree outlives this result and cannot change during it.
    unsafe { &(*cursor.node).value }
}
