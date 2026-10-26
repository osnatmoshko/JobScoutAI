import os
from datetime import date

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from agent_core import run_job_agent, validate_api_key_presence

st.set_page_config(page_title="Job Scout AI", page_icon="🧭", layout="wide")
st.title("🧭 Job Scout AI")
st.subheader("סוכן חכם לחיפוש, דירוג והרחבת חיפוש משרות פיתוח")
st.write(
    "הסוכן משתמש ב־Groq כמודל AI ובכלי חיפוש חיצוניים שמביאים מודעות ממקורות ציבוריים. "
    "הוא מדרג את המשרות, בוחן את התוצאות ומחליט אם להרחיב את החיפוש או לעצור."
)

with st.sidebar:
    st.header("הגדרות הסוכן")
    api_key = st.text_input(
        "מפתח Groq API",
        type="password",
        value=os.environ.get("GROQ_API_KEY", ""),
        help="זה חייב להיות מפתח שנוצר ב־Groq Console.",
    )
    st.divider()
    location = st.text_input("מיקום מועדף", value="ישראל")
    remote = st.selectbox(
        "העדפת עבודה",
        ["הכול (כולל משרות מרחוק)", "מרחוק בלבד", "משרד או היברידי"],
    )
    experience = st.selectbox(
        "רמת ניסיון",
        ["ג׳וניור / תחילת הדרך", "סטודנטית", "עד שנתיים ניסיון", "פתוחה גם למשרות אחרות"],
    )
    max_rounds = st.slider("מספר סבבי החלטה לכל היותר", min_value=1, max_value=3, value=2)

with st.form("job_search_form"):
    col1, col2 = st.columns(2)
    with col1:
        skills = st.text_area(
            "טכנולוגיות וכישורים",
            value="C#, .NET, Angular, React, JavaScript, Node.js, SQL, Python",
            height=90,
        )
        roles = st.text_input(
            "תפקידים מבוקשים",
            value="Junior Full Stack Developer, Backend Developer, Frontend Developer",
        )
    with col2:
        experience_details = st.text_area(
            "ניסיון ופרויקטים רלוונטיים",
            value="ניסיון פיתוח Full Stack בפרויקט במשרד החינוך עם C#, .NET, Angular; פרויקטים ב-React, Node.js ו-Python.",
            height=90,
        )
        exclusions = st.text_input("מה לא לכלול? (אופציונלי)", value="משרות בכירות, ניהול צוות")
    submitted = st.form_submit_button("🔎 הפעלת הסוכן", type="primary", use_container_width=True)

if submitted:
    if not validate_api_key_presence(api_key):
        st.error("לא נמצא מפתח Groq. הזיני מפתח Groq תקין.")
    elif not skills.strip() or not roles.strip():
        st.error("צריך למלא לפחות כישורים ותפקידים מבוקשים.")
    else:
        profile = {
            "location": location.strip() or "ישראל",
            "remote": remote,
            "experience_level": experience,
            "skills": [item.strip() for item in skills.replace("\n", ",").split(",") if item.strip()],
            "roles": [item.strip() for item in roles.split(",") if item.strip()],
            "experience_details": experience_details.strip(),
            "exclusions": exclusions.strip(),
        }
        status = st.status("הסוכן מתחיל לעבוד...", expanded=True)
        try:
            result = run_job_agent(
                api_key=api_key.strip() or os.environ.get("GROQ_API_KEY", ""),
                profile=profile,
                max_rounds=max_rounds,
                on_event=lambda message: status.write(message),
            )
            status.update(label="הסוכן סיים בהצלחה!", state="complete", expanded=False)

            st.markdown("## 📊 תוצאות הסוכן (ממוינות לפי ציון התאמה)")
            st.info(result["decision_summary"])
            
            # מיון בסדר יורד - משרה עם ציון 100/100 תופיע ראשונה
            jobs = sorted(result.get("jobs", []), key=lambda j: j.get("score", 0), reverse=True)

            st.caption(
                f"סבבי החלטה: {result['rounds']} · "
                f"משרות מוצגות: {len(jobs)} · "
                f"תאריך הרצה: {date.today().strftime('%d/%m/%Y')}"
            )

            if jobs:
                for idx, job in enumerate(jobs[:8], start=1):
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([4, 1.5, 1])
                        with c1:
                            st.markdown(f"**{idx}. {job.get('title', 'תפקיד פיתוח')}** @ *{job.get('company', 'חברה')}*")
                            st.caption(f"📍 {job.get('location', 'מרחוק')} | 🏷️ {', '.join(job.get('technologies', [])[:5])}")
                        with c2:
                            score = int(job.get('score', 0))
                            st.metric("ציון התאמה", f"{score}/100")
                        with c3:
                            url = job.get("job_url", "")
                            if url.startswith("https://"):
                                st.link_button("🔗 מודעה מקורית", url)
            else:
                st.warning("לא נמצאו משרות מתאימות במאגרים שנבדקו.")

            with st.expander("🧠 תהליך קבלת ההחלטות של הסוכן (Trace)"):
                for event in result["trace"]:
                    st.write("• " + event)

        except Exception as exc:
            status.update(label="ההרצה נכשלה", state="error", expanded=True)
            st.error("לא הצלחנו להשלים את החיפוש.")
            st.code(str(exc))

st.divider()
st.caption("Job Scout AI — מבדק פיתוח אג'נטים (משרד החינוך)")