// SPDX-License-Identifier: Apache-2.0

mod provider;
use provider::*;
use std::pin::pin;

fn main() {
    {
        let first = owner_new(65);
        let second = owner_new(66);
        {
            let ready = pin!(Head::new());
            let active = pin!(Head::new());
            ready_init(ready.as_ref());
            active_init(active.as_ref());
            ready_insert(ready.as_ref(), &first);
            ready_insert(ready.as_ref(), &second);
            active_insert(active.as_ref(), &first);
            active_insert(active.as_ref(), &second);
            assert_eq!(ready_count(ready.as_ref()), 2);
            assert_eq!(active_count(active.as_ref()), 2);
            let mut cursor = ready_first(ready.as_ref());
            let end = ready_end(ready.as_ref());
            let mut count = 0;
            while !cursor_equal(&cursor, &end) {
                // Both owners and heads remain live. No edit occurs during this loan.
                let value = unsafe { cursor_value(&cursor) };
                assert!((65..=66).contains(value));
                count += 1;
                // The current node is live and its payload loan has ended.
                unsafe {
                    cursor_advance(&mut cursor);
                }
            }
            assert_eq!(count, 2);
            drop(first);
            assert_eq!(ready_count(ready.as_ref()), 1);
            assert_eq!(active_count(active.as_ref()), 1);
            {
                let replacement = owner_new(67);
                ready_insert(ready.as_ref(), &replacement);
                active_insert(active.as_ref(), &replacement);
            }
            assert_eq!(ready_count(ready.as_ref()), 1);
            assert_eq!(active_count(active.as_ref()), 1);
            let mut cursor = ready_first(ready.as_ref());
            // Only second remains. No other payload reference is live.
            let value = unsafe { cursor_mut(&mut cursor) };
            *value = 68;
        }
        assert_eq!(*owner_value(&second), 68);
    }
    println!("OK");
}
