# utils.py

import smtplib
from email.message import EmailMessage

def send_email_with_attachment(to_email, file_path):
    msg = EmailMessage()
    msg["Subject"] = "Delivery Route Sheet"
    msg["From"] = "your_email@gmail.com"
    msg["To"] = to_email
    msg.set_content("Please find your delivery route sheet attached.")

    with open(file_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="octet-stream", filename=file_path.split("/")[-1])

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login("your_email@gmail.com", "your_app_password")  # use app password
        smtp.send_message(msg)