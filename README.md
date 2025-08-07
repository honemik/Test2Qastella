# Test2Qastella
Making question bank for qastella

The application expects a question bank to be a JSON object structured by subject and source. Each subject contains one or more sources (e.g., year or category), and each source is an array of question objects. A question object can include:

id: Numeric identifier

type: "single", "multiple", or "short"

question: The prompt text

options (optional): Key–value pairs of answer choices

answer: Correct choice(s)

images (optional): Array of base64-encoded image data

Example:

{
  "subjects": {
    "Biology": {
      "2024": [
        {
          "id": 1,
          "type": "single",
          "question": "1+1=?",
          "options": { "A": "1", "B": "2" },
          "answer": "B",
          "images": ["data:image/png;base64,..."]
        }
      ]
    }
  }
}
