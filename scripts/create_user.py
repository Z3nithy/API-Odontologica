import argparse
from getpass import getpass

from sqlalchemy import func

from core.senha_hash import criar_hash_senha
from database import Base, SessionLocal, engine
from models import Clinic, User

ROLES = ("receptionist", "dentist", "manager")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cria uma conta de equipe sem expor a senha nos argumentos do terminal."
    )
    parser.add_argument("--clinic", required=True, help="Nome da clínica.")
    parser.add_argument("--name", required=True, help="Nome da pessoa.")
    parser.add_argument("--email", required=True, help="E-mail de acesso.")
    parser.add_argument("--role", required=True, choices=ROLES, help="Perfil da conta.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    password = getpass("Senha (mínimo 12 caracteres): ")
    confirmation = getpass("Confirme a senha: ")
    if len(password) < 12:
        raise SystemExit("A senha precisa ter pelo menos 12 caracteres.")
    if password != confirmation:
        raise SystemExit("As senhas não conferem.")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        email = args.email.strip().lower()
        if db.query(User).filter(func.lower(User.email) == email).first():
            raise SystemExit("Já existe uma conta com este e-mail.")
        clinic_name = " ".join(args.clinic.split())
        clinic = (
            db.query(Clinic)
            .filter(func.lower(Clinic.name) == clinic_name.lower())
            .first()
        )
        if clinic is None:
            clinic = Clinic(name=clinic_name)
            db.add(clinic)
            db.flush()
        user = User(
            clinic_id=clinic.id,
            name=" ".join(args.name.split()),
            email=email,
            password_hash=criar_hash_senha(password),
            role=args.role,
            active=True,
        )
        db.add(user)
        db.commit()
        print(f"Conta criada para {user.name} ({user.role}) na clínica {clinic.name}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
