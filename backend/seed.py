"""Optional development seed. Run: python seed.py after configuring JWT_SECRET."""
from app.database import Base,engine,SessionLocal
from app.models import User,Case,Finding,Audit
from app.security import hash_password
Base.metadata.create_all(engine);db=SessionLocal()
if not db.query(User).filter_by(email='demo@healthtrace.local').first():
 user=User(email='demo@healthtrace.local',password_hash=hash_password('DemoPassword123!'));db.add(user);db.flush();case=Case(public_id='HT-10482',patient_name='John Anderson',condition='Knee Osteoarthritis',procedure='Advanced Knee Intervention',owner_id=user.id,complexity=82);db.add(case);db.flush();db.add(Finding(case_id=case.id,criterion='Conservative treatment ≥ 6 weeks',status='match',requirement='Conservative treatment must be completed for at least six weeks.',fact='Physiotherapy duration',value='8 weeks',rule='physiotherapy_duration ≥ 6 weeks',explanation='Synthetic seed evidence meets policy threshold.'));db.add(Audit(case_id=case.id,actor=user.email,action='Seeded synthetic case',target='HT-10482'));db.commit()
db.close()
