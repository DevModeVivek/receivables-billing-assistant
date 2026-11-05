"""AI Assistant: one assistant over the receivables reports and the live billing queue."""
import streamlit as st

from ai import context as ai_context
from ai import guard, providers
from ai.providers import AIError
from views import common as ui

ui.filter_controls()
m = ui.metrics()
conn = ui.workspace()
customers = ui.customers()
page_from = st.session_state.get("assistant_from")
provider = ui.ai_provider()

ui.header("AI assistant", "Ask about receivables or the request queue. Answers use only the app's calculated "
                          "figures.")

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
for msg in st.session_state["chat"]:
    with st.chat_message(msg["role"], avatar=AVATAR[msg["role"]]):
        st.markdown(ui.esc(msg["content"]))

system = ai_context.system_prompt(m, conn, customers, ui.now(), page_from)

if question and provider is not None:
    question = guard.clean_question(question)
    with st.chat_message("user", avatar=AVATAR["user"]):
        st.markdown(ui.esc(question))
    with st.chat_message("assistant", avatar=AVATAR["assistant"]):
        if guard.looks_like_injection(question):
            answer = guard.REFUSAL
            st.markdown(answer)
            st.session_state["chat"] += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        elif (wait := guard.check_rate(st.session_state)):
            st.info(wait, icon=":material/hourglass_top:")
        else:
            history = st.session_state["chat"][-8:] + [{"role": "user", "content": question}]
            try:
                with st.spinner("Reading the figures..."):
                    answer = ui.ai_answer(system, history)
                st.write_stream(ui.type_out(answer))
            except AIError:
                # Never a red error: show the figures Python calculated, clearly labelled as not AI.
                answer = ai_context.calculated_summary(m, conn)
                st.caption("The AI is busy right now, so here is the calculated summary from the report pages. "
                           "Ask again in a minute for a written answer.")
                st.markdown(ui.esc(answer))
                answer = "(Calculated summary, not AI)\n\n" + answer
            st.session_state["chat"] += [{"role": "user", "content": question},
                                         {"role": "assistant", "content": answer}]

if provider is not None:
    st.caption("AI-generated and can be wrong; check figures on the report pages. Questions are processed by a hosted "
               "AI service, so please use demo questions only.")
if st.session_state["chat"] and st.button("New conversation", icon=":material/add_comment:"):
    st.session_state["chat"] = []
    st.rerun()

ui.footer()
