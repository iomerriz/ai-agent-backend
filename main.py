from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import SessionLocal, engine
import models, schemas, auth
from groq import Groq
import os

import os

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
models.Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "http://localhost:5173",
    "https://ai-agent-frontend-lovat.vercel.app",
],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

#registering a user
@app.post("/register", response_model=schemas.UserResponse)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(models.User).filter(models.User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail = "Email already registered")
    
    hashed_pw = auth.hash_password(user.password)

    db_user = models.User(
        name = user.name,
        age = user.age,
        email = user.email,
        password = hashed_pw 
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user
    


# ============================================
# GET /users - Retrieve all users
# ============================================
# Purpose: Get a list of every registered user in the system
# What it does:
#   1. Queries the database for ALL users
#   2. Orders them by ID (ascending order)
#   3. Returns the complete list
# Response: Returns an array of user objects (without passwords)
# Example: GET http://localhost:8000/users
#          Returns: [{"id": 1, "name": "John", "age": 25, "email": "john@example.com"}, ...]
@app.get("/users", response_model=list[schemas.UserResponse])
def get_users(db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    # Query all users from the database, ordered by ID
    users = db.query(models.User).order_by(models.User.id).all()
    # Return the list of users (password is excluded by response_model)
    return users


# Return the signed-in user's profile as a single object.
@app.get("/users/me", response_model=schemas.UserResponse)
def get_my_profile(db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    user = db.query(models.User).filter(models.User.email == current_user).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# ============================================
# PUT /users/{user_id} - Update an existing user
# ============================================
# Purpose: Completely replace/update a user's information
# What it does:
#   1. Takes a user_id from the URL (which user to update)
#   2. Takes new user data from the request body (name, age, email)
#   3. Finds the user in the database
#   4. If user exists, updates their information
#   5. If user doesn't exist, returns a 404 error
#   6. Saves the changes to the database
# Response: Returns the updated user object
# Example: PUT http://localhost:8000/users/5
#          Body: {"name": "Jane Smith", "age": 31, "email": "jane.new@example.com"}
#          Returns: Updated user with new information
# Note: This is a FULL update - it replaces ALL fields
@app.put("/users/{user_id}" , response_model = schemas.UserResponse)
def update_user(user_id: int, updated_user: schemas.UserCreate, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    # Find the user to update
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    # If user doesn't exist, return error
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update the user's fields with the new data
    user.name = updated_user.name      # Change name
    user.age = updated_user.age        # Change age
    user.email = updated_user.email    # Change email
    # Note: Password is NOT updated here (security reason)
    
    # Save changes to the database
    db.commit()     # Permanently save the changes
    db.refresh(user) # Get the updated version from database
    
    # Return the updated user
    return user


# ============================================
# DELETE /users/{user_id} - Remove a user
# ============================================
# Purpose: Permanently delete a user from the system
# What it does:
#   1. Takes a user_id from the URL (which user to delete)
#   2. Finds the user in the database
#   3. If user exists, deletes them permanently
#   4. If user doesn't exist, returns a 404 error
#   5. Saves the deletion to the database
# Response: Returns a success message
# Example: DELETE http://localhost:8000/users/5
#          Returns: {"message": "user 5 deleted successfully"}
# Warning: This is PERMANENT - there's no undo!
#          Consider using a "soft delete" (mark as inactive) in real apps
@app.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session= Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    # Find the user to delete
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    # If user doesn't exist, return error
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Delete the user from the database
    db.delete(user)  # Mark for deletion
    db.commit()      # Permanently remove from database
    
    # Return success message
    return {"message": f"user {user_id} deleted successfully" }


@app.post("/login") 
def login(credentials: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == credentials.email).first()

    if not user or not auth.verify_password(credentials.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token = auth.create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

# groq chat endpoint
@app.post("/chat", response_model=schemas.ChatResponse)
def chat(request: schemas.ChatRequest, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    try:
        user = db.query(models.User).filter(models.User.email == current_user).first()

        # Create new conversation if no conversation_id provided
        if request.conversation_id is None:
            conv = models.Conversation(
                title=request.message[:50],
                user_id=user.id
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)
            conversation_id = conv.id
        else:
            conversation_id = request.conversation_id

        # Save user message
        user_message = models.Message(
            conversation_id=conversation_id,
            role="user",
            content=request.message
        )
        db.add(user_message)
        db.commit()

        # Get AI response
        response = groq_client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": request.message}]
        )
        ai_reply = response.choices[0].message.content

        # Save AI message
        ai_message = models.Message(
            conversation_id=conversation_id,
            role="ai",
            content=ai_reply
        )
        db.add(ai_message)
        db.commit()

        return {"reply": ai_reply, "conversation_id": conversation_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Create a new conversation
@app.post("/conversations", response_model=schemas.ConversationResponse)
def create_conversation(conv: schemas.ConversationCreate, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    user = db.query(models.User).filter(models.User.email == current_user).first()
    db_conv = models.Conversation(title=conv.title, user_id=user.id)
    db.add(db_conv)
    db.commit()
    db.refresh(db_conv)
    return db_conv


# Get all conversations for logged in user
@app.get("/conversations", response_model=list[schemas.ConversationResponse])
def get_conversations(db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    user = db.query(models.User).filter(models.User.email == current_user).first()
    conversations = db.query(models.Conversation).filter(models.Conversation.user_id == user.id).order_by(models.Conversation.created_at.desc()).all()
    return conversations


# Get a single conversation with all messages
@app.get("/conversations/{conversation_id}", response_model=schemas.ConversationResponse)
def get_conversation(conversation_id: int, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    user = db.query(models.User).filter(models.User.email == current_user).first()
    conv = db.query(models.Conversation).filter(
        models.Conversation.id == conversation_id,
        models.Conversation.user_id == user.id
    ).first()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv    

@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db), current_user: str = Depends(auth.get_current_user)):
    user = db.query(models.User).filter(models.User.email == current_user).first()
    conv = db.query(models.Conversation).filter(
        models.Conversation.id == conversation_id,
        models.Conversation.user_id == user.id
    ).first()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conv)
    db.commit()
    return {"message": "Conversation deleted"}
