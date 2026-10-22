# Datathon 2026, Reto Personas Mayores

Se puede ver el reto en el pdf 2026... el reto es el primero que se expone en él. Nuestra idea es hacer una especie de RAG, asumiendo un escenario en el que este sistema/app móvil estará conectado y "leyendo" las entradas de notificaciones de la Sede Electrónica. La idea es que esta app, dada una notificación de la Sede, notifique al señor por el móvil y le explique la notificación, te apareca en un chat el pdf para descargar y lo explique someramente, haciendo una parte explicativa e informativa de la misma, para que la pueda entender, explicando repercusiones para el notificado, posibles acciones respecto de la misma y plazos para ellas. Si existe alguna otra sección o forma de expresar la información proponla. También tendrá el papel de "asistente" jurídico o antofraude, en el sentido de: el usuario podrá explicar/pegar/recitar un correo/sms/mensaje/foto de una carta recibido y su fuente (la parte de hablar por voz queda para un futuro, pero es la idea) y preguntar qué tipo de notificación es, de qué se trata. Si es algún tipo de fraude o no, etc. La obligación del asistente será resovler esas dudas, deicrle de si se trata de una notificación relevante respecto de algo, si se trata de un fraude o negocio sospechoso (notificación SMS de un banco, oferta de bienes del hogar a precios o interés abusico, etc), explicarle si es un intento de fraude e ignorarlo, si es una notificación seria y cómo actuar y en qué plazos (buscar abogados en su zona incluso, otorgarle números de información pública en caso de que sea útil, etc etc, los casos que se te ocurrar). La idea es hacer una especie de RAG, llamar mediante langchain por ejemplo a algún modelo pequeño de claude y quelea la notificación(pdf) subido o "recibido por la sede" y escriba una explicación con información o acciones y plazos para proceder. Una cuestión es qué leyes y pdf subirle que puedan ser útiles, entiendo que la constitución puede ser una, ya que cualquier usario puede tener una duda acerca de la misma. Encontrar los pdfs relevantes es una tarea.

## Tareas
* Construir escenarios y casos de uso
* Encontrar documentación relevante para el rag


### Escenarios y casos de uso

* Dada una notificación establer un flujo de trabajo con la misma, (un árbol: fraude/no fraude notificación informativa/... en caso de requerir alguna acción como proceder etc, hay que pensar las clases) Estas notificaciones deben de ser automáticas según se recibe la notificación 
* Dada una duda del usuario acerca de un SMS, correo, llamada sospechos, carta lo que sea. Analizar el contenido y decir

### Documentos a añadir al RAG

Por definir, están en un word con link 

1. Normativa general 

Ley 39/2015, de 1 de octubre, del Procedimiento Administrativo Común de las Administraciones Públicas 

https://www.boe.es/buscar/pdf/2015/BOE-A-2015-10565-consolidado.pdf 

 
Es la norma principal sobre las notificaciones administrativas electrónicas. Regula: 

Las personas obligadas a relacionarse electrónicamente con la Administración, especialmente empresas, entidades sin personalidad jurídica, profesionales colegiados y representantes. 

El contenido y los requisitos de las notificaciones. 

La práctica de la notificación mediante comparecencia en sede electrónica o a través de la Dirección Electrónica Habilitada Única, DEHú. 

Los avisos enviados al correo electrónico o dispositivo indicado. 

Los efectos del acceso, rechazo o falta de acceso a la notificación. Son especialmente relevantes los artículos 14 y 40 a 44. [boe.es], [sede.admin...cas.gob.es] 

Ley 40/2015, de 1 de octubre, de Régimen Jurídico del Sector Público 

https://www.boe.es/buscar/pdf/2015/BOE-A-2015-10566-consolidado.pdf 

 
Regula el funcionamiento electrónico interno de las Administraciones Públicas, la identificación de sus órganos, la firma electrónica, la actuación administrativa automatizada y las relaciones electrónicas entre Administraciones. [boe.es] 

Real Decreto 203/2021, de 30 de marzo 
Desarrolla las leyes anteriores y concreta el funcionamiento de: 

Las sedes electrónicas. 

La Carpeta Ciudadana. 

La Dirección Electrónica Habilitada Única. 

Los registros electrónicos. 

Los avisos de puesta a disposición. 

La identificación y firma electrónica. 

El acceso a expedientes y notificaciones. [boe.es], [boe.es] 

https://www.boe.es/buscar/pdf/2021/BOE-A-2021-5032-consolidado.pdf 

 

Reglamento (UE) n.º 910/2014, conocido como Reglamento eIDAS 
Regula la identificación electrónica y los servicios de confianza, como los certificados electrónicos, la firma electrónica, el sello electrónico y los servicios de entrega electrónica certificada. [boe.es] 

https://www.boe.es/doue/2014/257/L00073-00114.pdf 

Ley 6/2020, de 11 de noviembre, reguladora de determinados aspectos de los servicios electrónicos de confianza 
Complementa en España el Reglamento eIDAS y regula determinados aspectos relativos a los certificados, firmas electrónicas y prestadores de servicios de confianza. 

https://www.boe.es/buscar/pdf/2020/BOE-A-2020-14046-consolidado.pdf 

Reglamento General de Protección de Datos y Ley Orgánica 3/2018, de Protección de Datos Personales y garantía de los derechos digitales 
Se aplican al tratamiento de los datos personales incluidos en las notificaciones, al control de acceso, a la confidencialidad y a la seguridad de la información. 

https://www.boe.es/doue/2016/119/L00001-00088.pdf 

https://www.boe.es/buscar/pdf/2018/BOE-A-2018-16673-consolidado.pdf 

Materias de notificaciones electrónicas para una persona jubilada mayor de 65 años (ámbito estatal) 

Pensión de jubilación y pensiones no contributivas 

Reconocimiento, revisión, revalorización y complementos de la pensión. 

Ley: Real Decreto Legislativo 8/2015, por el que se aprueba la Ley General de la Seguridad Social. [boe.es] 

https://www.boe.es/buscar/pdf/2015/BOE-A-2015-11724-consolidado.pdf 

Dependencia 

Reconocimiento del grado de dependencia, revisiones y recursos. 

Ley: Ley 39/2006, de Promoción de la Autonomía Personal y Atención a las Personas en Situación de Dependencia.   

https://www.boe.es/buscar/pdf/2006/BOE-A-2006-21990-consolidado.pdf 

Prestaciones y servicios de dependencia 

Teleasistencia, ayuda a domicilio, centros de día, residencias y prestaciones económicas. 

Ley: Real Decreto 1051/2013.   

https://www.boe.es/buscar/pdf/2013/BOE-A-2013-13811-consolidado.pdf 

 

Discapacidad 

Reconocimiento y revisión del grado de discapacidad. 

Ley: Real Decreto Legislativo 1/2013, Ley General de los Derechos de las Personas con Discapacidad.  

 https://www.boe.es/buscar/pdf/2013/BOE-A-2013-12632-consolidado.pdf 

 

Prestaciones sanitarias 

Reintegro de gastos sanitarios, prestaciones ortoprotésicas y ayudas técnicas. 

Ley: Ley 16/2003, de Cohesión y Calidad del Sistema Nacional de Salud.  

 https://www.boe.es/buscar/pdf/2003/BOE-A-2003-10715-consolidado.pdf 

 

Tributos e impuestos 

IRPF, requerimientos, devoluciones y liquidaciones tributarias. 

Ley: Ley 58/2003, General Tributaria.  

https://www.boe.es/buscar/pdf/2003/BOE-A-2003-23186-consolidado.pdf 

 

Herencias y sucesiones 

Impuesto sobre Sucesiones, comprobación de valores y documentación hereditaria. 

Ley: Ley 29/1987, del Impuesto sobre Sucesiones y Donaciones.  

https://www.boe.es/buscar/pdf/1987/BOE-A-1987-28141-consolidado.pdf 

 

Catastro y bienes heredados 

Cambios de titularidad de inmuebles heredados. 

Ley: Texto Refundido de la Ley del Catastro Inmobiliario.  

https://www.boe.es/buscar/pdf/2004/BOE-A-2004-4163-consolidado.pdf 

 

Tráfico y sanciones 

Multas, recursos y procedimientos relacionados con vehículos o permisos. 

Ley: Real Decreto Legislativo 6/2015, Ley sobre Tráfico y Seguridad Vial.   

https://www.boe.es/buscar/act.php?id=BOE-A-2015-11722 

 
