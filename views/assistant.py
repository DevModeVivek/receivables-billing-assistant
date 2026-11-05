"""AI Assistant: one assistant over the receivables reports and the live billing queue.

Every answer has the same parts (see ai/answer.py), and every amount and percentage in it is checked against the
app's own figures before it is shown.
"""
import streamlit as st

from ai import answer as fmt
from ai import context as ai_context
from ai import guard
from ai.providers import AIError
from views import common as ui

ui.filter_controls()
m = ui.metrics()
conn = ui.workspace()
customers = ui.customers()
page_from = st.session_state.get("assistant_from")
provider = ui.ai_provider()

ui.header("AI assistant", "Ask about receivables or the request queue. Answers use only the app's calculated "
                          "figures, and every amount is checked before it is shown.")

if provider is None:
    st.info("The assistant is offline right now. Every report and workflow step still works.",
            icon=":material/info:")

st.session_state.setdefault("chat", [])
pending = st.session_state.pop("assistant_pending", None)
question = st.chat_input("Ask about billing, collections or the request queue", disabled=provider is None,
                         max_chars=guard.MAX_QUESTION_CHARS) or pending

if not st.session_state["chat"] and not question:
    st.markdown("**Try asking**")
    cols = st.columns(2)
    for i, q in enumerate(ai_context.suggestions(page_from, conn)):
        cols[i % 2].button(q, key=f"sugg{i}", width="stretch", disabled=provider is None,
                           on_click=lambda q=q: st.session_state.update(assistant_pending=q))

AVATAR = {"user": ":material/person:", "assistant": ":material/smart_toy:"}


def show(msg: dict, i: int, follow_ups: bool) -> None:
    if msg.get("data"):
        ui.render_answer(msg["data"], key=str(i), follow_ups=follow_ups)
    else:
        if msg.get("note"):
            st.caption(msg["note"])
        st.markdown(ui.esc(msg["content"]))


chat = st.session_state["chat"]
for i, msg in enumerate(chat):
    with st.chat_message(msg["role"], avatar=AVATAR[msg["role"]]):
        show(msg, i, follow_ups=i == len(chat) - 1 and not question)

system = ai_context.system_prompt(m, conn, customers, ui.now(), page_from)

if question and provider is not None:
    question = guard.clean_question(question)
    with st.chat_message("user", avatar=AVATAR["user"]):
        st.markdown(ui.esc(question))
    with st.chat_message("assistant", avatar=AVATAR["assistant"]):
        reply = None
        if guard.looks_like_injection(question):
            reply = {"role": "assistant", "content": guard.REFUSAL}
        elif (wait := guard.check_rate(st.session_state)):
            st.info(wait, icon=":material/hourglass_top:")
        else:
            history = [{"role": c["role"], "content": c["content"]} for c in chat[-8:]] + \
                      [{"role": "user", "content": question}]
            try:
                with st.spinner("Reading the figures and checking them..."):
                    data = ui.ai_answer(system, history)
                reply = {"role": "assistant", "content": fmt.to_markdown(data), "data": data}
            except AIError:
                # Never a red error: show the figures Python calculated, clearly labelled as not AI.
                reply = {"role": "assistant", "content": ai_context.calculated_summary(m, conn),
                         "note": "The AI is busy right now, so here is the calculated summary from the report pages. "
                                 "Ask again in a minute for a written answer."}
        if reply:
            chat += [{"role": "user", "content": question}, reply]
            show(reply, len(chat) - 1, follow_ups=True)

if provider is not None:
    st.caption("AI-generated and can be wrong; amounts are checked against the app's figures, but please review "
               "before use. Questions are processed by a hosted AI service, so use demo questions only.")
if chat and st.button("New conversation", icon=":material/add_comment:"):
    st.session_state["chat"] = []
    st.rerun()
ui.footer()
