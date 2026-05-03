from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
import os, json, datetime, random, string
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = 'studyai-secret-key-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///studyai.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
ALLOWED_EXTENSIONS = {'pdf', 'txt', 'docx', 'pptx', 'png', 'jpg', 'jpeg'}

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# ── Models ──────────────────────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    study_streak = db.Column(db.Integer, default=0)
    last_active = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    courses = db.relationship('Course', backref='user', lazy=True, cascade='all, delete-orphan')
    quizzes = db.relationship('QuizAttempt', backref='user', lazy=True, cascade='all, delete-orphan')

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    color = db.Column(db.String(20), default='#6366f1')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    materials = db.relationship('Material', backref='course', lazy=True, cascade='all, delete-orphan')
    topics = db.relationship('Topic', backref='course', lazy=True, cascade='all, delete-orphan')

class Topic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    mastery = db.Column(db.Float, default=0.0)
    materials = db.relationship('Material', backref='topic', lazy=True)

class Material(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(300), nullable=False)
    original_name = db.Column(db.String(300), nullable=False)
    content_text = db.Column(db.Text)
    key_concepts = db.Column(db.Text)  # JSON
    summary = db.Column(db.Text)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    topic_id = db.Column(db.Integer, db.ForeignKey('topic.id'), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    file_type = db.Column(db.String(20))
    flashcards = db.relationship('Flashcard', backref='material', lazy=True, cascade='all, delete-orphan')
    quizzes = db.relationship('Quiz', backref='material', lazy=True, cascade='all, delete-orphan')

class Flashcard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    front = db.Column(db.Text, nullable=False)
    back = db.Column(db.Text, nullable=False)
    material_id = db.Column(db.Integer, db.ForeignKey('material.id'), nullable=False)
    known = db.Column(db.Boolean, default=False)
    times_reviewed = db.Column(db.Integer, default=0)
    difficulty = db.Column(db.String(20), default='medium')

class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    questions = db.Column(db.Text)  # JSON
    material_id = db.Column(db.Integer, db.ForeignKey('material.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    attempts = db.relationship('QuizAttempt', backref='quiz', lazy=True)

class QuizAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    score = db.Column(db.Float, nullable=False)
    answers = db.Column(db.Text)  # JSON
    taken_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    time_taken = db.Column(db.Integer, default=0)  # seconds

class StudyPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plan_data = db.Column(db.Text)  # JSON
    generated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    week_start = db.Column(db.Date)

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    tags = db.Column(db.String(500))

class Reminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    due_date = db.Column(db.DateTime, nullable=False)
    completed = db.Column(db.Boolean, default=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=True)

# ── Helpers ──────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Not authenticated'}), 401
        return f(*args, **kwargs)
    return decorated

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_file(filepath, ext):
    """Extract plain text from uploaded file."""
    try:
        if ext == 'txt':
            with open(filepath, 'r', errors='ignore') as f:
                return f.read()
        elif ext == 'pdf':
            try:
                import PyPDF2
                text = ''
                with open(filepath, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        text += page.extract_text() or ''
                return text
            except Exception:
                return "[PDF content - install PyPDF2 for text extraction]"
        elif ext in ('docx',):
            try:
                import docx
                doc = docx.Document(filepath)
                return '\n'.join([p.text for p in doc.paragraphs])
            except Exception:
                return "[DOCX content - install python-docx for text extraction]"
        else:
            return ""
    except Exception as e:
        return f"[Could not extract text: {str(e)}]"

# ── Auth Routes ───────────────────────────────────────────────────────────────

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already registered'}), 400
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username taken'}), 400
    pw = bcrypt.generate_password_hash(data['password']).decode('utf-8')
    user = User(username=data['username'], email=data['email'], password_hash=pw)
    db.session.add(user)
    db.session.commit()
    session['user_id'] = user.id
    session['username'] = user.username
    return jsonify({'message': 'Registered', 'user': {'id': user.id, 'username': user.username, 'email': user.email}})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(email=data['email']).first()
    if not user or not bcrypt.check_password_hash(user.password_hash, data['password']):
        return jsonify({'error': 'Invalid credentials'}), 401
    session['user_id'] = user.id
    session['username'] = user.username
    user.last_active = datetime.datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'Logged in', 'user': {'id': user.id, 'username': user.username, 'email': user.email}})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out'})

@app.route('/api/me')
def me():
    if 'user_id' not in session:
        return jsonify({'authenticated': False})
    user = User.query.get(session['user_id'])
    return jsonify({'authenticated': True, 'user': {'id': user.id, 'username': user.username, 'email': user.email, 'streak': user.study_streak}})

# ── Courses ───────────────────────────────────────────────────────────────────

@app.route('/api/courses', methods=['GET'])
@login_required
def get_courses():
    courses = Course.query.filter_by(user_id=session['user_id']).all()
    result = []
    for c in courses:
        result.append({
            'id': c.id, 'name': c.name, 'description': c.description,
            'color': c.color, 'created_at': c.created_at.isoformat(),
            'material_count': len(c.materials),
            'topic_count': len(c.topics)
        })
    return jsonify(result)

@app.route('/api/courses', methods=['POST'])
@login_required
def create_course():
    data = request.json
    course = Course(name=data['name'], description=data.get('description', ''),
                    color=data.get('color', '#6366f1'), user_id=session['user_id'])
    db.session.add(course)
    db.session.commit()
    return jsonify({'id': course.id, 'name': course.name, 'message': 'Course created'})

@app.route('/api/courses/<int:cid>', methods=['DELETE'])
@login_required
def delete_course(cid):
    course = Course.query.filter_by(id=cid, user_id=session['user_id']).first_or_404()
    db.session.delete(course)
    db.session.commit()
    return jsonify({'message': 'Deleted'})

@app.route('/api/courses/<int:cid>/topics', methods=['GET'])
@login_required
def get_topics(cid):
    topics = Topic.query.filter_by(course_id=cid).all()
    return jsonify([{'id': t.id, 'name': t.name, 'mastery': t.mastery} for t in topics])

@app.route('/api/courses/<int:cid>/topics', methods=['POST'])
@login_required
def create_topic(cid):
    data = request.json
    topic = Topic(name=data['name'], course_id=cid)
    db.session.add(topic)
    db.session.commit()
    return jsonify({'id': topic.id, 'name': topic.name})

# ── Materials ─────────────────────────────────────────────────────────────────

@app.route('/api/materials/upload', methods=['POST'])
@login_required
def upload_material():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    course_id = request.form.get('course_id')
    topic_id = request.form.get('topic_id')
    if not file or not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type'}), 400
    
    ext = file.filename.rsplit('.', 1)[1].lower()
    uid = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    safe_name = f"{uid}_{secure_filename(file.filename)}"
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], safe_name)
    file.save(filepath)
    
    content = extract_text_from_file(filepath, ext)
    
    mat = Material(
        filename=safe_name, original_name=file.filename,
        content_text=content[:10000],  # store first 10k chars
        course_id=course_id, topic_id=topic_id or None,
        file_type=ext
    )
    db.session.add(mat)
    db.session.commit()
    return jsonify({'id': mat.id, 'name': mat.original_name, 'message': 'Uploaded'})

@app.route('/api/courses/<int:cid>/materials', methods=['GET'])
@login_required
def get_materials(cid):
    mats = Material.query.filter_by(course_id=cid).all()
    return jsonify([{
        'id': m.id, 'original_name': m.original_name,
        'file_type': m.file_type, 'uploaded_at': m.uploaded_at.isoformat(),
        'has_concepts': bool(m.key_concepts), 'has_summary': bool(m.summary),
        'topic_id': m.topic_id
    } for m in mats])

@app.route('/api/materials/<int:mid>', methods=['DELETE'])
@login_required
def delete_material(mid):
    mat = Material.query.get_or_404(mid)
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], mat.filename))
    except Exception:
        pass
    db.session.delete(mat)
    db.session.commit()
    return jsonify({'message': 'Deleted'})

# ── AI: Process Material ──────────────────────────────────────────────────────

@app.route('/api/materials/<int:mid>/process', methods=['POST'])
@login_required
def process_material(mid):
    """Call Anthropic API to extract key concepts and generate summary."""
    mat = Material.query.get_or_404(mid)
    if not mat.content_text or len(mat.content_text.strip()) < 20:
        return jsonify({'error': 'Not enough text content to process'}), 400
    
    import requests as req
    prompt = f"""You are an expert study assistant. Analyze the following study material and extract:
1. A concise summary (2-3 sentences)
2. A list of 5-10 key concepts (as JSON array of strings)
3. Important terms and definitions (as JSON object)

Study Material:
{mat.content_text[:4000]}

Respond ONLY with valid JSON in this exact format:
{{
  "summary": "...",
  "key_concepts": ["concept1", "concept2", ...],
  "terms": {{"term1": "definition1", "term2": "definition2", ...}}
}}"""
    
    try:
        resp = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}]
            }, timeout=30
        )
        data = resp.json()
        text = ''.join(b.get('text','') for b in data.get('content',[]) if b.get('type')=='text')
        text = text.strip().lstrip('```json').lstrip('```').rstrip('```').strip()
        parsed = json.loads(text)
        mat.summary = parsed.get('summary','')
        mat.key_concepts = json.dumps({
            'concepts': parsed.get('key_concepts', []),
            'terms': parsed.get('terms', {})
        })
        db.session.commit()
        return jsonify({'summary': mat.summary, 'key_concepts': parsed.get('key_concepts', []), 'terms': parsed.get('terms', {})})
    except Exception as e:
        return jsonify({'error': f'AI processing failed: {str(e)}'}), 500

# ── AI: Generate Quiz ────────────────────────────────────────────────────────

@app.route('/api/materials/<int:mid>/generate-quiz', methods=['POST'])
@login_required
def generate_quiz(mid):
    mat = Material.query.get_or_404(mid)
    data = request.json or {}
    num_q = data.get('num_questions', 5)
    q_type = data.get('type', 'mixed')  # mc, truefalse, mixed
    
    import requests as req
    prompt = f"""You are an expert educator. Create a quiz from this study material.
Generate {num_q} questions of type: {q_type} (mc=multiple choice, truefalse=true/false, mixed=both).

Study Material:
{mat.content_text[:3000]}

Respond ONLY with valid JSON:
{{
  "title": "Quiz on [topic]",
  "questions": [
    {{
      "type": "mc",
      "question": "Question text?",
      "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
      "correct": 0,
      "explanation": "Why this is correct"
    }},
    {{
      "type": "truefalse",
      "question": "Statement...",
      "correct": true,
      "explanation": "Explanation"
    }}
  ]
}}"""
    
    try:
        import requests as req
        resp = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 1000,
                  "messages": [{"role": "user", "content": prompt}]}, timeout=30
        )
        rdata = resp.json()
        text = ''.join(b.get('text','') for b in rdata.get('content',[]) if b.get('type')=='text')
        text = text.strip().lstrip('```json').lstrip('```').rstrip('```').strip()
        parsed = json.loads(text)
        quiz = Quiz(title=parsed['title'], questions=json.dumps(parsed['questions']), material_id=mid)
        db.session.add(quiz)
        db.session.commit()
        return jsonify({'id': quiz.id, 'title': quiz.title, 'questions': parsed['questions']})
    except Exception as e:
        return jsonify({'error': f'Quiz generation failed: {str(e)}'}), 500

@app.route('/api/quizzes/<int:qid>', methods=['GET'])
@login_required
def get_quiz(qid):
    quiz = Quiz.query.get_or_404(qid)
    return jsonify({'id': quiz.id, 'title': quiz.title, 'questions': json.loads(quiz.questions)})

@app.route('/api/quizzes/<int:qid>/submit', methods=['POST'])
@login_required
def submit_quiz(qid):
    quiz = Quiz.query.get_or_404(qid)
    data = request.json
    answers = data.get('answers', [])
    time_taken = data.get('time_taken', 0)
    questions = json.loads(quiz.questions)
    
    correct = 0
    results = []
    for i, q in enumerate(questions):
        user_ans = answers[i] if i < len(answers) else None
        is_correct = str(user_ans) == str(q['correct'])
        if is_correct:
            correct += 1
        results.append({'correct': is_correct, 'user_answer': user_ans,
                        'correct_answer': q['correct'], 'explanation': q.get('explanation','')})
    
    score = (correct / len(questions)) * 100 if questions else 0
    attempt = QuizAttempt(quiz_id=qid, user_id=session['user_id'],
                          score=score, answers=json.dumps(results), time_taken=time_taken)
    db.session.add(attempt)
    db.session.commit()
    return jsonify({'score': score, 'correct': correct, 'total': len(questions), 'results': results})

@app.route('/api/quizzes/history', methods=['GET'])
@login_required
def quiz_history():
    attempts = QuizAttempt.query.filter_by(user_id=session['user_id'])\
        .order_by(QuizAttempt.taken_at.desc()).limit(20).all()
    result = []
    for a in attempts:
        result.append({
            'id': a.id, 'quiz_title': a.quiz.title, 'score': a.score,
            'taken_at': a.taken_at.isoformat(), 'time_taken': a.time_taken
        })
    return jsonify(result)

# ── AI: Flashcards ────────────────────────────────────────────────────────────

@app.route('/api/materials/<int:mid>/generate-flashcards', methods=['POST'])
@login_required
def generate_flashcards(mid):
    mat = Material.query.get_or_404(mid)
    import requests as req
    prompt = f"""Create 8-12 flashcards from this study material for memorization practice.

Study Material:
{mat.content_text[:3000]}

Respond ONLY with valid JSON:
{{
  "flashcards": [
    {{"front": "Question or term", "back": "Answer or definition", "difficulty": "easy|medium|hard"}},
    ...
  ]
}}"""
    try:
        resp = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 1000,
                  "messages": [{"role": "user", "content": prompt}]}, timeout=30
        )
        rdata = resp.json()
        text = ''.join(b.get('text','') for b in rdata.get('content',[]) if b.get('type')=='text')
        text = text.strip().lstrip('```json').lstrip('```').rstrip('```').strip()
        parsed = json.loads(text)
        cards = []
        for fc in parsed.get('flashcards', []):
            card = Flashcard(front=fc['front'], back=fc['back'],
                             difficulty=fc.get('difficulty','medium'), material_id=mid)
            db.session.add(card)
            cards.append({'front': fc['front'], 'back': fc['back'], 'difficulty': fc.get('difficulty','medium')})
        db.session.commit()
        return jsonify({'flashcards': cards, 'count': len(cards)})
    except Exception as e:
        return jsonify({'error': f'Flashcard generation failed: {str(e)}'}), 500

@app.route('/api/courses/<int:cid>/flashcards', methods=['GET'])
@login_required
def get_flashcards(cid):
    mats = Material.query.filter_by(course_id=cid).all()
    cards = []
    for m in mats:
        for fc in m.flashcards:
            cards.append({'id': fc.id, 'front': fc.front, 'back': fc.back,
                          'known': fc.known, 'difficulty': fc.difficulty,
                          'times_reviewed': fc.times_reviewed, 'material': m.original_name})
    return jsonify(cards)

@app.route('/api/flashcards/<int:fid>/review', methods=['POST'])
@login_required
def review_flashcard(fid):
    data = request.json
    fc = Flashcard.query.get_or_404(fid)
    fc.known = data.get('known', False)
    fc.times_reviewed += 1
    db.session.commit()
    return jsonify({'message': 'Updated'})

# ── AI: Study Plan ────────────────────────────────────────────────────────────

@app.route('/api/study-plan/generate', methods=['POST'])
@login_required
def generate_study_plan():
    uid = session['user_id']
    courses = Course.query.filter_by(user_id=uid).all()
    attempts = QuizAttempt.query.filter_by(user_id=uid).order_by(QuizAttempt.taken_at.desc()).limit(30).all()
    
    course_data = []
    for c in courses:
        topics = [{'name': t.name, 'mastery': t.mastery} for t in c.topics]
        avg_score = 0
        course_attempts = [a for a in attempts if a.quiz and a.quiz.material and a.quiz.material.course_id == c.id]
        if course_attempts:
            avg_score = sum(a.score for a in course_attempts) / len(course_attempts)
        course_data.append({'name': c.name, 'topics': topics, 'avg_score': avg_score, 'material_count': len(c.materials)})
    
    import requests as req
    prompt = f"""You are an expert academic advisor. Create a personalized weekly study plan.

Student's courses and performance:
{json.dumps(course_data, indent=2)}

Create a 7-day study plan focusing on weak areas. Respond ONLY with JSON:
{{
  "week_theme": "Focus area for the week",
  "days": [
    {{
      "day": "Monday",
      "sessions": [
        {{"course": "Course name", "topic": "Topic to study", "duration_min": 45, "activity": "Review notes / Practice problems / Flashcards", "priority": "high|medium|low"}}
      ],
      "total_minutes": 90
    }}
  ],
  "tips": ["Study tip 1", "Study tip 2", "Study tip 3"]
}}"""
    
    try:
        resp = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 1000,
                  "messages": [{"role": "user", "content": prompt}]}, timeout=30
        )
        rdata = resp.json()
        text = ''.join(b.get('text','') for b in rdata.get('content',[]) if b.get('type')=='text')
        text = text.strip().lstrip('```json').lstrip('```').rstrip('```').strip()
        parsed = json.loads(text)
        plan = StudyPlan(user_id=uid, plan_data=json.dumps(parsed),
                         week_start=datetime.date.today())
        db.session.add(plan)
        db.session.commit()
        return jsonify(parsed)
    except Exception as e:
        return jsonify({'error': f'Study plan generation failed: {str(e)}'}), 500

@app.route('/api/study-plan/latest', methods=['GET'])
@login_required
def get_latest_plan():
    plan = StudyPlan.query.filter_by(user_id=session['user_id'])\
        .order_by(StudyPlan.generated_at.desc()).first()
    if not plan:
        return jsonify(None)
    return jsonify(json.loads(plan.plan_data))

# ── AI: Translation ───────────────────────────────────────────────────────────

@app.route('/api/translate', methods=['POST'])
@login_required
def translate_text():
    data = request.json
    text = data.get('text', '')
    target_lang = data.get('language', 'Spanish')
    
    import requests as req
    prompt = f"Translate the following study material to {target_lang}. Preserve formatting and technical terms where appropriate.\n\nText to translate:\n{text[:2000]}"
    
    try:
        resp = req.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 1000,
                  "messages": [{"role": "user", "content": prompt}]}, timeout=30
        )
        rdata = resp.json()
        translated = ''.join(b.get('text','') for b in rdata.get('content',[]) if b.get('type')=='text')
        return jsonify({'translated': translated, 'language': target_lang})
    except Exception as e:
        return jsonify({'error': f'Translation failed: {str(e)}'}), 500

# ── Analytics ────────────────────────────────────────────────────────────────

@app.route('/api/analytics', methods=['GET'])
@login_required
def get_analytics():
    uid = session['user_id']
    attempts = QuizAttempt.query.filter_by(user_id=uid).order_by(QuizAttempt.taken_at).all()
    courses = Course.query.filter_by(user_id=uid).all()
    
    score_trend = [{'date': a.taken_at.strftime('%Y-%m-%d'), 'score': a.score,
                    'quiz': a.quiz.title if a.quiz else 'Quiz'} for a in attempts[-30:]]
    
    course_performance = []
    for c in courses:
        c_attempts = [a for a in attempts if a.quiz and a.quiz.material and a.quiz.material.course_id == c.id]
        avg = sum(a.score for a in c_attempts) / len(c_attempts) if c_attempts else 0
        course_performance.append({'course': c.name, 'avg_score': round(avg, 1),
                                    'attempts': len(c_attempts), 'color': c.color})
    
    total_flashcards = 0
    known_flashcards = 0
    for c in courses:
        for m in c.materials:
            total_flashcards += len(m.flashcards)
            known_flashcards += sum(1 for fc in m.flashcards if fc.known)
    
    return jsonify({
        'score_trend': score_trend,
        'course_performance': course_performance,
        'total_quizzes': len(attempts),
        'avg_score': round(sum(a.score for a in attempts) / len(attempts), 1) if attempts else 0,
        'total_materials': sum(len(c.materials) for c in courses),
        'total_flashcards': total_flashcards,
        'known_flashcards': known_flashcards,
        'total_courses': len(courses)
    })

# ── Notes ────────────────────────────────────────────────────────────────────

@app.route('/api/notes', methods=['GET'])
@login_required
def get_notes():
    notes = Note.query.filter_by(user_id=session['user_id']).order_by(Note.updated_at.desc()).all()
    return jsonify([{'id': n.id, 'title': n.title, 'content': n.content,
                     'updated_at': n.updated_at.isoformat(), 'tags': n.tags,
                     'course_id': n.course_id} for n in notes])

@app.route('/api/notes', methods=['POST'])
@login_required
def create_note():
    data = request.json
    note = Note(title=data['title'], content=data.get('content',''),
                user_id=session['user_id'], course_id=data.get('course_id'),
                tags=data.get('tags',''))
    db.session.add(note)
    db.session.commit()
    return jsonify({'id': note.id, 'message': 'Note created'})

@app.route('/api/notes/<int:nid>', methods=['PUT'])
@login_required
def update_note(nid):
    note = Note.query.filter_by(id=nid, user_id=session['user_id']).first_or_404()
    data = request.json
    note.title = data.get('title', note.title)
    note.content = data.get('content', note.content)
    note.tags = data.get('tags', note.tags)
    note.updated_at = datetime.datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'Updated'})

@app.route('/api/notes/<int:nid>', methods=['DELETE'])
@login_required
def delete_note(nid):
    note = Note.query.filter_by(id=nid, user_id=session['user_id']).first_or_404()
    db.session.delete(note)
    db.session.commit()
    return jsonify({'message': 'Deleted'})

# ── Reminders ────────────────────────────────────────────────────────────────

@app.route('/api/reminders', methods=['GET'])
@login_required
def get_reminders():
    reminders = Reminder.query.filter_by(user_id=session['user_id'])\
        .order_by(Reminder.due_date).all()
    return jsonify([{'id': r.id, 'title': r.title, 'due_date': r.due_date.isoformat(),
                     'completed': r.completed, 'course_id': r.course_id} for r in reminders])

@app.route('/api/reminders', methods=['POST'])
@login_required
def create_reminder():
    data = request.json
    r = Reminder(user_id=session['user_id'], title=data['title'],
                 due_date=datetime.datetime.fromisoformat(data['due_date']),
                 course_id=data.get('course_id'))
    db.session.add(r)
    db.session.commit()
    return jsonify({'id': r.id, 'message': 'Reminder created'})

@app.route('/api/reminders/<int:rid>/complete', methods=['POST'])
@login_required
def complete_reminder(rid):
    r = Reminder.query.filter_by(id=rid, user_id=session['user_id']).first_or_404()
    r.completed = True
    db.session.commit()
    return jsonify({'message': 'Completed'})

# ── Search ───────────────────────────────────────────────────────────────────

@app.route('/api/search', methods=['GET'])
@login_required
def search():
    q = request.args.get('q', '').lower()
    if not q:
        return jsonify([])
    uid = session['user_id']
    results = []
    for c in Course.query.filter_by(user_id=uid).all():
        if q in c.name.lower() or (c.description and q in c.description.lower()):
            results.append({'type': 'course', 'id': c.id, 'title': c.name, 'subtitle': 'Course'})
        for m in c.materials:
            if q in m.original_name.lower() or (m.content_text and q in m.content_text.lower()):
                results.append({'type': 'material', 'id': m.id, 'title': m.original_name,
                                'subtitle': f'Material in {c.name}'})
    for n in Note.query.filter_by(user_id=uid).all():
        if q in n.title.lower() or (n.content and q in n.content.lower()):
            results.append({'type': 'note', 'id': n.id, 'title': n.title, 'subtitle': 'Note'})
    return jsonify(results[:20])

# ── Static / SPA ─────────────────────────────────────────────────────────────

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    return render_template('index.html')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
