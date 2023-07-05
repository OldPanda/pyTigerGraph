from pyTigerGraph.pyTigerGraphException import TigerGraphException
from pyTigerGraph.pyTigerGraph import TigerGraphConnection
from dataclasses import dataclass, make_dataclass, fields, _MISSING_TYPE
from typing import List, Dict, Union
from datetime import datetime
import json
import hashlib
import warnings

BASE_TYPES  = ["string", "int", "uint", "float", "double", "bool", "datetime"]
PRIMARY_ID_TYPES = ["string", "int", "uint", "datetime"]
COLLECTION_TYPES = ["list", "set", "map"]
COLLECTION_VALUE_TYPES = ["int", "double", "float", "string", "datetime", "udt"]
MAP_KEY_TYPES = ["int", "string", "datetime"]

def _parse_type(attr):
    collection_types = ""
    if attr["AttributeType"].get("ValueTypeName"):
        if attr["AttributeType"].get("KeyTypeName"):
            collection_types += "<"+ attr["AttributeType"].get("KeyTypeName") + "," + attr["AttributeType"].get("ValueTypeName") + ">"
        else:
            collection_types += "<"+attr["AttributeType"].get("ValueTypeName") + ">"
    attr_type = (attr["AttributeType"]["Name"] + collection_types).upper()
    return attr_type

def _get_type(attr_type):
    if attr_type == "STRING":
        return str
    elif attr_type == "INT":
        return int
    elif attr_type == "FLOAT":
        return float
    elif "LIST" in attr_type:
        val_type = attr_type.split("<")[1].strip(">")
        return List[_get_type(val_type)]
    elif "MAP" in attr_type:
        key_val = attr_type.split("<")[1].strip(">")
        key_type = key_val.split(",")[0]
        val_type = key_val.split(",")[1]
        return Dict[_get_type(key_type), _get_type(val_type)]
    elif attr_type == "BOOL":
        return bool
    elif attr_type == "datetime":
        return datetime
    else:
        return attr_type


def _py_to_tg_type(attr_type):
    if attr_type == str:
        return "STRING"
    elif attr_type == int:
        return "INT"
    elif attr_type == float:
        return "FLOAT"
    elif attr_type == list:
        raise TigerGraphException("Must define value type within list")
    elif attr_type == dict:
        raise TigerGraphException("Must define key and value types within dictionary/map")
    elif attr_type == datetime:
        return "DATETIME"
    elif (str(type(attr_type)) == "<class 'typing._GenericAlias'>") and attr_type._name == "List":
        val_type = _py_to_tg_type(attr_type.__args__[0])
        if val_type.lower() in COLLECTION_VALUE_TYPES:
            return "LIST<"+val_type+">"
        else:
            raise TigerGraphException(val_type + " not a valid type for the value type in LISTs.")
    elif (str(type(attr_type)) == "<class 'typing._GenericAlias'>") and attr_type._name == "Dict":
        key_type = _py_to_tg_type(attr_type.__args__[0])
        val_type = _py_to_tg_type(attr_type.__args__[1])
        if key_type.lower() in MAP_KEY_TYPES:
            if val_type.lower() in COLLECTION_VALUE_TYPES:
                return "MAP<"+key_type+","+val_type+">"
            else:
                raise TigerGraphException(val_type + " not a valid type for the value type in MAPs.")
        else:
            raise TigerGraphException(key_type + " not a valid type for the key type in MAPs.")
    else:
        if str(attr_type).lower() in BASE_TYPES:
            return str(attr_type).upper()
        else:
            raise TigerGraphException(attr_type+"not a valid TigerGraph datatype.")



@dataclass
class Vertex(object):
    # TODO: I shouldn't have to run this, only use default value specified in dataclass
    @classmethod
    def define_primary_id(self, primary_id, primary_id_as_attribute):
        self.primary_id = primary_id
        self.primary_id_as_attribute = primary_id_as_attribute
        self.primary_id_type = self.__annotations__[primary_id]
        if not(_py_to_tg_type(self.primary_id_type).lower() in PRIMARY_ID_TYPES):
            raise TigerGraphException(self.primary_id_type, "is not a supported type for primary IDs.")

    def __init_subclass__(cls):
        # TODO: Fill edge type info
        cls.incoming_edge_types = []
        cls.outgoing_edge_types = []
        cls._attribute_edits = {"ADD": {}, "DELETE": {}}

    @classmethod
    def _set_incoming_edge_types(self, e_types):
        self.incoming_edge_types = e_types

    @classmethod
    def _set_outgoing_edge_types(self, e_types):
        self.outgoing_edge_types = e_types

    @classmethod
    def _set_attr_edit(self, add:dict = None, delete:dict = None):
        if add:
            self._attribute_edits["ADD"].update(add)
        if delete:
            self._attribute_edits["DELETE"].update(delete)

    @classmethod
    def _get_attr_edit(self):
        return self._attribute_edits


    @classmethod
    def add_attribute(self, attribute_name, attribute_type, default_value = None):
        if attribute_name in self._get_attr_edit()["ADD"].keys():
            warnings.warn(attribute_name + " already in staged edits. Overwriting previous edits.")
        for attr in self.attributes:
            if attr == attribute_name:
                raise TigerGraphException(attribute_name + " already exists as an attribute on "+self.__name__ + " vertices")
        attr_type = _py_to_tg_type(attribute_type)
        gsql_add = "ALTER VERTEX "+self.__name__+" ADD ATTRIBUTE ("+attribute_name+" "+attr_type
        if default_value:
            if attribute_type == str:
                gsql_add += " DEFAULT '"+default_value+"'"
            else:
                gsql_add += " DEFAULT "+str(default_value)
        gsql_add +=");"
        self._set_attr_edit(add ={attribute_name: gsql_add})

    @classmethod
    def remove_attribute(self, attribute_name):
        if self.primary_id_as_attribute:
            if attribute_name == self.primary_id:
                raise TigerGraphException("Cannot remove primary ID attribute: "+self.primary_id+".")
        removed = False
        for attr in self.attributes:
            if attr == attribute_name:
                self._set_attr_edit(delete = {attribute_name: "ALTER VERTEX "+self.__name__+" DROP ATTRIBUTE ("+attribute_name+");"})
                removed = True
        if not(removed):
            raise TigerGraphException("An attribute of "+ attribute_name + " is not an attribute on "+ self.__name__ + " vertices")

    @classmethod
    @property
    def attributes(self):
        return self.__annotations__

    def __getattr__(self, attr):
        if self.attributes.get(attr):
            return self.attributes.get(attr)
        else:
            raise TigerGraphException("No attribute named "+ attr + "for vertex type " + self.vertex_type)

    def __eq__(self, lhs):
        return isinstance(lhs, Vertex) and lhs.vertex_type == self.vertex_type
    
    def __repr__(self):
        return self.vertex_type

@dataclass
class Edge:
    # TODO: Handle discriminators
    def __init_subclass__(cls):
        # TODO: Make sure is_directed, reverse_edge, from, and to are defined.
        cls._attribute_edits = {"ADD": {}, "DELETE": {}}
        cls.is_directed:bool
        cls.reverse_edge:Union[str, bool]
        cls.from_vertex_types:Union[Vertex, List[Vertex]]
        cls.to_vertex_types:Union[Vertex, List[Vertex]]

    @classmethod
    def _set_attr_edit(self, add:dict = None, delete:dict = None):
        if add:
            self._attribute_edits["ADD"].update(add)
        if delete:
            self._attribute_edits["DELETE"].update(delete)

    @classmethod
    def _get_attr_edit(self):
        return self._attribute_edits

    @classmethod
    def add_attribute(self, attribute_name, attribute_type, default_value = None):
        if attribute_name in self._get_attr_edit()["ADD"].keys():
            warnings.warn(attribute_name + " already in staged edits. Overwriting previous edits.")
        for attr in self.attributes:
            if attr == attribute_name:
                raise TigerGraphException(attribute_name + " already exists as an attribute on "+self.__name__ + " edges")
        attr_type = _py_to_tg_type(attribute_type)
        gsql_add = "ALTER EDGE "+self.__name__+" ADD ATTRIBUTE ("+attribute_name+" "+attr_type
        if default_value:
            if attribute_type == str:
                gsql_add += " DEFAULT '"+default_value+"'"
            else:
                gsql_add += " DEFAULT "+str(default_value)
        gsql_add +=");"
        self._set_attr_edit(add ={attribute_name: gsql_add})

    @classmethod
    def remove_attribute(self, attribute_name):
        removed = False
        for attr in self.attributes:
            if attr == attribute_name:
                self._set_attr_edit(delete = {attribute_name:"ALTER EDGE "+self.__name__+" DROP ATTRIBUTE ("+attribute_name+");"})
                removed = True
        if not(removed):
            raise TigerGraphException("An attribute of "+ attribute_name + " is not an attribute on "+ self.__name__ + " edges")

    @classmethod
    @property
    def attributes(self):
        return self.__annotations__

    def __getattr__(self, attr):
        if self.attributes.get(attr):
            return self.attributes.get(attr)
        else:
            raise TigerGraphException("No attribute named "+ attr + "for edge type " + self.edge_type)

    def __eq__(self, lhs):
        return isinstance(lhs, Edge) and lhs.edge_type == self.edge_type and lhs.from_vertex_type == self.from_vertex_type and lhs.to_vertex_type == self.to_vertex_type

    def __repr__(self):
        return self.edge_type

class Graph():
    def __init__(self, conn:TigerGraphConnection = None):
        self._vertex_types = {}
        self._edge_types = {}
        self._vertex_edits = {"ADD": {}, "DELETE": {}}
        self._edge_edits = {"ADD": {}, "DELETE": {}}
        if conn:
            db_rep = conn.getSchema(force=True)
            self.graphname = db_rep["GraphName"]
            for v_type in db_rep["VertexTypes"]:
                vert = make_dataclass(v_type["Name"],
                                    [(attr["AttributeName"], _get_type(_parse_type(attr)), None) for attr in v_type["Attributes"]] + 
                                    [(v_type["PrimaryId"]["AttributeName"], _get_type(_parse_type(v_type["PrimaryId"])), None),
                                     ("primary_id", str, v_type["PrimaryId"]["AttributeName"]),
                                     ("primary_id_as_attribute", bool, v_type["PrimaryId"]["PrimaryIdAsAttribute"])],
                                    bases=(Vertex,), repr=False)
                self._vertex_types[v_type["Name"]] = vert

            for e_type in db_rep["EdgeTypes"]:
                e = make_dataclass(e_type["Name"],
                                    [(attr["AttributeName"], _get_type(_parse_type(attr)), None) for attr in e_type["Attributes"]] + 
                                    [("from_vertex", self._vertex_types[e_type["FromVertexTypeName"]], None),
                                     ("to_vertex", self._vertex_types[e_type["FromVertexTypeName"]], None),
                                     ("is_directed", bool, e_type["IsDirected"]),
                                     ("reverse_edge", str, e_type["Config"].get("REVERSE_EDGE"))],
                                    bases=(Edge,), repr=False)
                self._edge_types[e_type["Name"]] = e
            self.conn = conn

    def add_vertex_type(self, vertex: Vertex, outdegree_stats=True):
        if vertex.__name__ in self._vertex_types.keys():
            raise TigerGraphException(vertex.__name__+" already exists in the database")
        if vertex.__name__ in self._vertex_edits.keys():
            warnings.warn(vertex.__name__ + " already in staged edits. Overwriting previous edits.")
        gsql_def = "ADD VERTEX "+vertex.__name__+"("
        attrs = vertex.attributes
        try:
            primary_id = vertex.primary_id
            primary_id_type = vertex.primary_id_type
            primary_id_as_attr = vertex.primary_id_as_attribute
        except:
            raise TigerGraphException("Primary ID not defined. Run Vertex.define_primary_id() to define the Primary ID")
        gsql_def += "PRIMARY_ID "+primary_id+" "+_py_to_tg_type(primary_id_type)
        for attr in attrs.keys():
            if attr == primary_id:
                continue
            else:
                gsql_def += ", "
                gsql_def += attr + " "+_py_to_tg_type(attrs[attr])
        gsql_def += ")"
        if outdegree_stats:
            gsql_def += ' WITH STATS="OUTDEGREE_BY_EDGETYPE"'
        if outdegree_stats and primary_id_as_attr:
            gsql_def += ", "
        if primary_id_as_attr:
            gsql_def += 'PRIMARY_ID_AS_ATTRIBUTE="true"'
        gsql_def += ";"
        self._vertex_edits["ADD"][vertex.__name__] = gsql_def

    def add_edge_type(self, edge: Edge):
        if edge in self._edge_types.values():
            raise TigerGraphException(edge.__name__+" already exists in the database")
        if edge in self._edge_edits.values():
            warnings.warn(edge.__name__ + " already in staged edits. Overwriting previous edits")
        attrs = edge.attributes
        is_directed = None
        reverse_edge = None
        for field in fields(edge):
            if field.name == "is_directed":
                is_directed = field.default
            if field.name == "reverse_edge":
                reverse_edge = field.default

        gsql_def = ""
        if is_directed:
            gsql_def += "ADD DIRECTED EDGE "+edge.__name__+"("
        else:
            gsql_def += "ADD UNDIRECTED EDGE "+edge.__name__+"("

        # TODO: Handle Unions for multiple vertex types given an edge type
        from_vert = edge.attributes["from_vertex"].__name__
        to_vert = edge.attributes["to_vertex"].__name__
        gsql_def += "FROM "+from_vert+", "+"TO "+to_vert
        for attr in attrs.keys():
            if attr == "from_vertex" or attr == "to_vertex" or attr == "is_directed" or attr == "reverse_edge":
                continue
            else:
                gsql_def += ", "
                gsql_def += attr + " "+_py_to_tg_type(attrs[attr])
        gsql_def += ")"

        if reverse_edge:
            if isinstance(reverse_edge, str):
                gsql_def += ' WITH REVERSE_EDGE="'+reverse_edge+'"'
            elif isinstance(reverse_edge, bool):
                gsql_def += ' WITH REVERSE_EDGE="reverse_'+edge.__name__+'"'
            else:
                raise TigerGraphException("Reverse edge name of type: "+str(type(attrs["reverse_edge"])+" is not supported."))
        gsql_def+=";"
        self._edge_edits["ADD"][edge.__name__] = gsql_def

    def remove_vertex_type(self, vertex: Vertex):
        gsql_def = "DROP VERTEX "+vertex.__name__+";"
        self._vertex_edits["DELETE"][vertex.__name__] = gsql_def

    def remove_edge_type(self, edge: Edge):
        gsql_def = "DROP EDGE "+edge.__name__+";"
        self._edge_edits["DELETE"][edge.__name__] = gsql_def

    def commit_changes(self, conn: TigerGraphConnection = None):
        if not(conn):
            if self.conn:
                conn = self.conn
            else:
                raise TigerGraphException("No Connection Defined. Please instantiate a TigerGraphConnection to the database to commit the schema.")
        all_attr = [x._attribute_edits for x in list(self._vertex_types.values()) + list(self._edge_types.values())]
        for elem in list(self._vertex_types.values()) + list(self._edge_types.values()): # need to remove the changes locally
            elem._attribute_edits = {"ADD": {}, "DELETE": {}}
        all_attribute_edits = {"ADD": {}, "DELETE": {}}
        for change in all_attr:
            all_attribute_edits["ADD"].update(change["ADD"])
            all_attribute_edits["DELETE"].update(change["DELETE"])
        md5 = hashlib.md5()
        md5.update(json.dumps({**self._vertex_edits, **self._edge_edits, **all_attribute_edits}).encode())
        job_name = "pytg_change_"+md5.hexdigest()
        start_gsql = "USE GRAPH "+conn.graphname+"\n"
        start_gsql += "DROP JOB "+job_name+"\n"
        start_gsql += "CREATE SCHEMA_CHANGE JOB " + job_name + " FOR GRAPH " + conn.graphname + " {\n"
        for v_to_add in self._vertex_edits["ADD"]:
            start_gsql += self._vertex_edits["ADD"][v_to_add] + "\n"
        for e_to_add in self._edge_edits["ADD"]:
            start_gsql += self._edge_edits["ADD"][e_to_add] + "\n"
        for v_to_drop in self._vertex_edits["DELETE"]:
            start_gsql += self._vertex_edits["DELETE"][v_to_drop] + "\n"
        for e_to_drop in self._edge_edits["DELETE"]:
            start_gsql += self._edge_edits["DELETE"][e_to_drop] + "\n"
        for attr_to_add in all_attribute_edits["ADD"]:
            start_gsql += all_attribute_edits["ADD"][attr_to_add] + "\n"
        for attr_to_drop in all_attribute_edits["DELETE"]:
            start_gsql += all_attribute_edits["DELETE"][attr_to_drop] +"\n"
        start_gsql += "}\n"
        start_gsql += "RUN SCHEMA_CHANGE JOB "+job_name
        res = conn.gsql(start_gsql)
        if "updated to new version" in res:
            self.__init__(conn)
        else:
            raise TigerGraphException("Schema change failed with message:\n"+res)

    @property
    def vertex_types(self):
        return self._vertex_types

    @property
    def edge_types(self):
        return self._edge_types