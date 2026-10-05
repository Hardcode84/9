// SPDX-License-Identifier: Apache-2.0

struct Ticket {
    code: i32,
}

impl Drop for Ticket {
    fn drop(&mut self) {
        print!("{}", char::from_u32(self.code as u32).unwrap());
    }
}

fn ticket_code(ticket: &Ticket) -> &i32 {
    &ticket.code
}

fn set_code(ticket: &mut Ticket, code: i32) {
    ticket.code = code;
}

fn main() {
    let first = Ticket { code: 65 };
    let mut ticket = first;
    let code = ticket_code(&ticket);
    assert_eq!(*code, 65);
    set_code(&mut ticket, 66);
    drop(ticket);
    {
        let _last = Ticket { code: 67 };
    }
    println!();
}
