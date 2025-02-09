from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html', active_page='home')

@app.route('/contact')
def contact():
    return render_template('contact.html', active_page='contact') # Ensure "contact.html" matches the filename exactly

@app.route('/submit', methods=['POST'])
def submit():
    name = request.form.get('name')
    email = request.form.get('email')
    message = request.form.get('message')
    print(f"Name: {name}, Email: {email}, Message: {message}")
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)
