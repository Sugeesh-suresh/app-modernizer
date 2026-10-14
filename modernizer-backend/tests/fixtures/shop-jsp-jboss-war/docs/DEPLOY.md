# Deploying shop.war to JBoss EAP / WildFly

1. Build: `mvn -B -DskipTests package` produces `target/shop.war`.
2. Make sure the Oracle JDBC driver module/deployment is installed and named `oracle`.
3. Create the datasource (set the real password through your secret store, never in the repo):
   `$JBOSS_HOME/bin/jboss-cli.sh --connect --file=deploy/jboss-datasource.cli`
4. Deploy: `$JBOSS_HOME/bin/jboss-cli.sh --connect "deploy target/shop.war --force"`
   (or copy it to `standalone/deployments/`).
5. Open `http://localhost:8080/shop/` (context root comes from `WEB-INF/jboss-web.xml`).

`WEB-INF/shop-ds.xml` is an alternative `-ds.xml` datasource definition for the same JNDI name.
The module `com.acme.shop.config` referenced in `jboss-deployment-structure.xml` must exist on the server.
