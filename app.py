from flask import Flask, render_template, request, redirect, url_for, send_file

app = Flask(__name__)

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
    return render_template('contact.html', active_page='contact')

@app.route('/submit', methods=['POST'])
def submit():
    name = request.form.get('name')
    email = request.form.get('email')
    message = request.form.get('message')
    print(f"Name: {name}, Email: {email}, Message: {message}")
    return redirect(url_for('home'))

@app.route('/portfolio')
def portfolio():
    return render_template('portfolio.html', active_page='portfolio')

if __name__ == '__main__':
    app.run(debug=True)
