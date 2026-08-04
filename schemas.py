from pydantic import BaseModel, EmailStr

class UserCreate(BaseModel):
    name: str
    age: int
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    name: str
    age: int
    email: EmailStr

class Config:
    from_attributes = True  

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class ChatRequest(BaseModel):
    message:str

class ChatResponse(BaseModel):
    reply:str              
