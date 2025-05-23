# Utilise une image Node.js officielle avec Debian
FROM node:20-bullseye

# Installe Python 3 et pip
RUN apt-get update && apt-get install -y python3 python3-pip

WORKDIR /app

# Copie le code source
COPY . .

# Installe les dépendances Python
RUN pip3 install --no-cache-dir -r requirements.txt

# Installe les dépendances Node.js (si package.json existe)
RUN if [ -f package.json ]; then npm install; fi

# Commande de démarrage du bot
CMD ["python3", "main.py"] 