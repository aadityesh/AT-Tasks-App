from .serializers import TaskSerializer
from datetime import datetime, timedelta

def parse_task_text(text):
    
    task = {}
    text_lower = text.lower()

    recurrence = ""
    if "every day" in text_lower:
        recurrence = "daily"
        
    elif "every week" in text_lower:
        recurrence = "weekly"
        
    elif "every month" in text_lower:
        recurrence = "month"
        
    elif "every year" in text_lower:
        recurrence = "yearly"
    
    due_today = datetime.now().date()
    
    if "tomorrow" in text_lower:
        due_today = due_today + timedelta(days=1)
    
    for word in text_lower.split(" "):
        if word[-2:] in ["st", "nd", "rd", "th"] and word[:-2].isdigit():
            due_today = due_today + timedelta(days=30)
            break
    
    task_data = {
        "title": "_".join(text),
        "description": text,
        "due_date": due_today,
        "recurrence": recurrence,
    }
    

    return task_data
    