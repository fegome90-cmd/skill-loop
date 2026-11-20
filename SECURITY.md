# Política de seguridad

## Versiones soportadas

Solo se mantiene la rama `main`. No hay versiones publicadas ni etiquetas: un
informe se aplica al commit que esté en `main` en ese momento.

## Cómo reportar

No abras un issue público. Usá el
[reporte privado de seguridad](https://github.com/fegome90-cmd/skill-loop/security/advisories/new)
e indicá:

- el archivo y el commit afectados;
- qué permite hacer el problema y en qué condiciones;
- cómo reproducirlo, si es posible.

Omití el valor de cualquier credencial. Si ya publicaste una, revocala en el
proveedor antes de avisar.

## Alcance

Cubre las vulnerabilidades del código propio y de las integraciones mantenidas
en este repositorio, incluidos `src/`, `tests/`, `plugins/`, `scripts/`,
`.github/`, `docs/` y la documentación. La enumeración no limita el alcance a
esas rutas.

Las skills vendorizadas en `.agents/skills/` conservan su licencia y su proyecto
de origen; los problemas exclusivos de ese código corresponden a su upstream. Si
el problema afecta a cómo se incorpora, configura o utiliza una dependencia en
este repositorio, se acepta su reporte privado aquí.

Los prototipos de `reference/` son material de lectura: no se ejecutan ni se
distribuyen.

## Controles automáticos

GitHub secret scanning y push protection están activos. El workflow
`Repository security` agrega:

- escaneo del historial con Gitleaks;
- política de nombres sensibles (`.env`, claves, credenciales, `.kube`,
  `.docker`);
- un hook local opcional.

No cubre binarios, archivos comprimidos ni mensajes de commit; esos casos
requieren revisión humana.

## Expectativas

Acuse de recibo en un plazo de cinco días hábiles. No hay compromiso de plazo de
corrección. Si lo pedís, se acredita el informe cuando se publique la corrección.
