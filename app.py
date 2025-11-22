from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import resend

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-fallback-secret')

# Email / Resend configuration
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
if not RESEND_API_KEY:
    raise RuntimeError("RESEND_API_KEY is not set in environment variables")

resend.api_key = RESEND_API_KEY

# Where you want to receive contact form emails
CONTACT_EMAIL = os.environ.get('EMAIL_USERNAME') or os.environ.get('CONTACT_EMAIL')
if not CONTACT_EMAIL:
    raise RuntimeError("Set EMAIL_USERNAME or CONTACT_EMAIL in environment variables")

# "From" shown in the email (Resend requires a verified domain for custom from address)
FROM_EMAIL = os.environ.get('RESEND_FROM_EMAIL', 'Portfolio Contact Form <onboarding@resend.dev>')

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

@app.route('/')
def home():
    return render_template('index.html', active_page='home')

@app.route('/blog')
def blog():
    # Example blog posts data - in real app, this would come from a database
    blog_posts = [
        {
            'id': 1,
            'title': 'Data Analytics Trends 2024',
            'date': 'January 15, 2024',
            'category': 'Analytics',
            'image': 'blog1.jpg',
            'excerpt': 'Exploring the latest trends in data analytics and their impact on business decisions...',
            'slug': 'data-analytics-trends-2024'
        },
        {
            'id': 2,
            'title': 'Power BI vs Tableau',
            'date': 'January 10, 2024',
            'category': 'Tools',
            'image': 'blog2.jpg',
            'excerpt': 'A comprehensive comparison of two leading data visualization tools...',
            'slug': 'powerbi-vs-tableau'
        }
    ]
    return render_template('blog.html', active_page='blog', posts=blog_posts)

@app.route('/blog/<slug>')
def blog_post(slug):
    # In real app, fetch the specific post from database using slug
    # For now, using dummy data
    post = {
        'title': 'Data Analytics Trends 2024',
        'date': 'January 15, 2024',
        'content': 'Full blog post content would go here...',
        'image': 'blog1.jpg'
    }
    return render_template('blog_post.html', post=post)

@app.route('/contact')
def contact():
    return render_template(
        'contact.html',
        active_page='contact',
        form_data=session.get('form_data', {})
    )

@app.route('/submit', methods=['POST'])
@limiter.limit("5 per minute")
def submit():
    # Store form data in session
    session['form_data'] = {
        'name': request.form.get('name', '').strip(),
        'email': request.form.get('email', '').strip(),
        'phone': request.form.get('phone', '').strip(),
        'subject': request.form.get('subject', '').strip(),
        'message': request.form.get('message', '').strip(),
    }

    try:
        # Get form data from session
        form_data = session['form_data']
        
        # Basic validation - only check if fields are not empty
        if not all([form_data['name'], form_data['email'], form_data['subject'], form_data['message']]):
            flash('Please fill in all required fields.', 'error')
            return redirect(url_for('contact'))

        # Email subject & body
        subject = f"New Contact Form Submission: {form_data['subject']}"
        body = f"""
New Contact Form Submission

━━━━━━━━━━━━━━━━━━━━━━━━━

👤 Sender Details:
   Name: {form_data['name']}
   Email: {form_data['email']}
   Phone: {form_data['phone']}

📝 Message Details:
   Subject: {form_data['subject']}

📨 Message:
{form_data['message']}

━━━━━━━━━━━━━━━━━━━━━━━━━

This message was sent from your portfolio website contact form.
"""

        # Send email using Resend
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [CONTACT_EMAIL],
            "subject": subject,
            "text": body,
        })

        # Clear form data from session on success
        session.pop('form_data', None)
        flash('Thanks for reaching out! I will get back to you within 24 hours.', 'success')
        return redirect(url_for('contact'))

    except Exception as e:
        print(f"Error sending email: {str(e)}")
        flash('Oops! Something went wrong. Please try again or email me directly at sayannaskar.web@gmail.com', 'error')
        return redirect(url_for('contact'))

@app.route('/portfolio')
def portfolio():
    return render_template('portfolio.html', active_page='portfolio')

@app.route('/biography')
def biography():
    return render_template('biography.html', active_page='biography')

if __name__ == '__main__':
    app.run(debug=True)
