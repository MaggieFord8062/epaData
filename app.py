from flask import Flask, render_template, request
from search import search_data


app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")

@app.route("/search")
def search():
    return render_template("search.html")

@app.route("/basic-search", methods=["GET", "POST"])
def basic_search():
    if request.method == "POST":
        search_parameters = request.form.to_dict()
        results = search_data(**search_parameters)
        return render_template("results.html", results=results)
    return render_template("basic_search.html")



@app.route("/advanced-search")
def advanced_search():
    return "Advanced Search page"


if __name__ == "__main__":
    app.run(debug=True)