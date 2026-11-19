# ADAM — formuler une hypothèse avant de l’éprouver

ADAM fait partie d’**AURUM** : **ARKS permet de retrouver et de vérifier les sources,
ADAM aide à formuler des hypothèses, puis les backtests les mettent à l’épreuve.**
Une citation exacte ne démontre pas un mécanisme, et une compilation réussie ne
constitue ni un résultat scientifique ni une autorisation de lancer un backtest.

Cette version publique est un **démonstrateur local hors ligne**. Elle conserve
les contrats de proposition, la vérification des citations et le noyau de
compilation déclarative d’ADAM. L’exemple du laboratoire **Luma** est entièrement
fictif : instrument `FIXTURE_NO_MARKET`, observation inventée, règles choisies pour
tester le format, aucune série de prix et aucun résultat de marché.

Le démonstrateur valide une proposition préparée. Il ne génère pas automatiquement
une hypothèse avec un modèle. L’interface NiceGUI privée, ses campagnes autonomes,
ses profils, son historique et ses connecteurs de production ne sont pas livrés.

## Installer

Parcours vérifié : **Windows, Python 3.14 64 bits**. Dans PowerShell, à la racine
de ce dépôt :

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-public.lock.txt
```

L’installation initiale télécharge six dépendances publiques depuis PyPI.
Les commandes de démonstration n’effectuent ensuite aucun appel réseau.
Aucune clé API, aucun SDK de modèle, aucun environnement ARKS ni dossier sur un
lecteur particulier n’est nécessaire.

## Essayer l’hypothèse fictive

```powershell
.\.venv\Scripts\python.exe -I -B tools\demo.py
```

Ouvrez `reports/public-demo/review.html` dans votre navigateur, ou utilisez
`LANCER_ADAM_DEMO.cmd` après installation. Cette page est autonome : pas de serveur,
pas de ressource externe, pas de script exécutant un modèle. Le lanceur CMD ouvre
le résultat HTML dans le navigateur par défaut.

Le parcours :

1. Charge `examples/proposal.json` et le contexte hôte séparé
   `examples/host-context.json`.
2. Contrôle la structure stricte, les identifiants de requête et le périmètre.
3. Matérialise la citation avec les octets exacts du passage fictif après les
   équivalences de mise en page autorisées par le code d’origine.
4. Dérive les champs du contrat, dont H0, et compile la règle avec le noyau livré.
5. Produit la proposition contrôlée, `validation.json`, `review.txt` et `review.html`.

Résultat attendu : `PASS_OUTPUT_CONTRACT_AND_NATIVE_COMPILATION_ONLY`.
`hypothesis_ready`, `canonical_registered` et `backtest_allowed` restent **false**.
Le mot PROPOSED dans le contrat désigne une proposition techniquement formalisée,
pas une stratégie éprouvée. Aucun backtest n’est exécuté.

Les résultats sont écrits sous `reports/`, exclu de Git. Le texte source de
l’exemple se trouve dans `examples/source-fictive.txt`.

## Modifier une proposition

Conservez le schéma et le périmètre du contexte hôte. Les entrées libres sont
des données à valider, jamais du code à exécuter :

```powershell
.\.venv\Scripts\python.exe -I -B tools\demo.py --proposal examples\proposal.json --context examples\host-context.json --output reports\mon-essai
.\.venv\Scripts\python.exe -I -B tools\demo.py --schema
```

Pour un travail personnel, placez les propositions et contextes dans un dossier
ignoré comme `hypotheses/`, sans remplacer les exemples publics par des idées réelles.
Les syntaxes prises en charge sont celles du compilateur livré ; les demandes hors
capacité doivent être explicitement refusées. Le moteur portefeuille n’est pas livré.

## ARKS : configuration et limites

Le parcours public **n’interroge pas ARKS**. Les passages fictifs utilisent les
champs attendus par le validateur : source et chunk, texte exact et SHA-256,
version documentaire, Evidence et localisateurs. Leur origine reste explicitement
`PUBLIC_SYNTHETIC_DEMO_ONLY` ; les noms techniques de provenance conservés dans
le contrat ne les transforment pas en retours réels d’ARKS.

Pour utiliser des passages réels, un programme hôte doit obtenir des résultats
ARKS autorisés, résoudre les Evidence, contrôler les droits et la fraîcheur, puis
construire un **contexte hôte distinct de la réponse du modèle**. Il fournit
`request_id`, `methodology`, `allowed_assets`, `allowed_timeframes`,
`research_identity`, `passages`, les profils de séance autorisés et, si nécessaire,
`personal_observation`. Ce fichier se passe avec `--context`.

Les identifiants du contrat ADAM suivent les formes `ARKS_SRC_...` et
`chk_` suivi de 64 caractères hexadécimaux. Il faut adapter explicitement le
format de sortie d’ARKS si son contrat diffère ; inventer un identifiant ou une
mention de résolution ne remplace pas la vérification de la source.
Le CLI contrôle le contenu de ce contexte, **pas sa signature ni sa collecte réelle**.

La liaison ARKS en direct, les droits d’un corpus réel et sa fraîcheur ne sont
pas testés ici. Les anciens adaptateurs privés ne sont pas copiés et aucune
variable de chemin n’active implicitement une connexion à l’installation privée.

## Modèles : configuration et limites

Cette copie ne contient ni fournisseur actif ni client API. Le démonstrateur et
les tests n’appellent aucun modèle, payant ou local. Il n’est pas nécessaire de
fournir `OPENAI_API_KEY` ou une autre clé.

Un modèle externe peut servir à **préparer séparément** une proposition JSON :
exportez le schéma avec `--schema`, fournissez au modèle uniquement les informations
que vous êtes autorisé à transmettre, et conservez les identifiants et le périmètre
fixés par l’hôte. Enregistrez sa réponse dans un dossier privé ignoré puis passez-la
avec `--proposal`. Le contexte hôte ne doit pas être choisi par le modèle.
ADAM effectuera les mêmes contrôles locaux ; il n’ajoute pas de droit de backtest.

Ce branchement manuel décrit le format d’entrée, sans garantir la compatibilité
avec un modèle particulier. Aucun modèle ni fournisseur réel n’a été validé.

## Tests réellement effectués

```powershell
.\.venv\Scripts\python.exe -I -B tools\run_public_checks.py
```

La suite contient **22 tests**, dont un groupe de **48 contrôles synthétiques**
repris du validateur d’origine : propositions SWING et DAY, compilation, identité
de requête, citations exactes, champs inattendus, refus d’autorisations et limites.
Elle vérifie aussi le parcours fictif livré, la répétabilité des empreintes,
les citations de mise en page, l’échappement HTML, le refus de réseau et de
sous-processus. Ces deux derniers tests provoquent volontairement des tentatives
refusées avant résolution réseau ou lancement.

Les tests ont été rejoués dans le dépôt de destination avec Python et ses
dépendances sur `C:`, sous audit refusant les accès à `F:`. Le résultat fictif a
aussi été contrôlé après copie dans un autre répertoire. Le lanceur CMD a été
relu ; le parcours Python a été exécuté sans tester un double-clic Windows.

Non testés : application privée complète, SDK de modèle, fournisseur réel,
connexion ARKS en direct, marchés, prix, sessions réelles, backtests ou transfert
vers l’installation AURUM. La garde Python hors ligne est un contrôle diagnostique,
pas une isolation système contre du code hostile.

## Composition et confidentialité

Le registre `output_contract_v1/PUBLIC_REGISTRY.json` et sa liaison au compilateur
ont été reconstruits uniquement à partir des fichiers livrés. Ce registre public
ne reprend pas le registre privé AURUM et ne crée aucune compatibilité implicite
avec celui-ci. Les empreintes contrôlent la cohérence locale, pas une signature.

Ne versionnez jamais hypothèses réelles, stratégies, corpus, campagnes, bases,
historiques, journaux, réglages personnels ou clés. `.gitignore` couvre leurs
emplacements standards ; vérifiez également le contenu des futurs ajouts.
Les environnements privés, configurations, sauvegardes et résultats source sont
exclus. Aucun historique Git source n’est copié.

## Licence et composants tiers

Le code AURUM/ADAM relève de `LICENSE.txt`, selon les mêmes conditions que la
licence ARKS consultée lors de cette préparation : **usage personnel, privé et
non commercial gratuit ; exploitation commerciale, même interne, sur accord
écrit préalable du titulaire des droits**. Les autres droits restent réservés.
Ce n’est pas une licence open source. Les demandes suivent le contact indiqué
dans la licence.

Les dépendances tierces conservent leurs propres licences, recensées dans
`THIRD_PARTY_NOTICES.md` avec les textes fournis dans `LICENSES/`.
Le corpus tiers de compétences scientifiques utilisé par l’installation privée
n’est pas livré. La licence ADAM ne remplace aucune licence de composant tiers.
